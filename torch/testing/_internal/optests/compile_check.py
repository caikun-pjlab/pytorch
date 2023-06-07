import torch
from .make_fx import make_fx_check
from .aot_autograd import aot_autograd_check
from torch._subclasses.schema_check_mode import SchemaCheckMode


def operator_compile_check(
        func,
        args,
        kwargs=None,
        *,
        dynamic_only=False,
        supports_autograd=True,
        fullgraph=True,
):
    """Check if torch.compile supports a custom operator.

    Args:
        func (function): an operator that takes at least one Tensor as input
            and returns a Tensor or a Tuple of Tensors.
        args (Tuple): args to the operator
        kwargs (dict, optional): kwargs to the operator
        dynamic_only (bool, optional): If the operator only works with dynamic
            shapes. This can happen if it returns Tensors whose shape are
            dependent on the data on the input Tensors. If True, we skip
            tests related to torch.compile with static shapes.
        supports_autograd (bool, optional): If the operator does not support
            autograd. If False, we will skip autograd-related tests.
        fullgraph (bool, optional): If we expect torch.compile to not graph
            break on seeing the operator. Graph breaks are bad for performance.

    """
    if kwargs is None:
        kwargs = {}

    # Add some clones to the beginning of func so that it is actually out-of-place.
    # A lot of our tests (e.g. aot_autograd_check) assume that the function passed
    # in is out-of-place and contains a call to the operator in being tested.
    func = add_clones(func)

    def run_static_or_dynamic_tests(dynamic):
        tracing_mode = 'symbolic' if dynamic else 'fake'
        make_fx_check(func, args, kwargs, tracing_mode=tracing_mode)
        if not supports_autograd:
            aot_autograd_check(func, args, kwargs, dynamic=dynamic)
        check_compile(func, args, kwargs, fullgraph=fullgraph, backend='aot_eager', dynamic=dynamic)
        check_compile(func, args, kwargs, fullgraph=fullgraph, backend='inductor', dynamic=dynamic)

    schema_check(func, args, kwargs)
    if not dynamic_only:
        run_static_or_dynamic_tests(dynamic=False)
    run_static_or_dynamic_tests(dynamic=True)


def add_clones(func):
    def clone_then_func(*args, **kwargs):
        args, kwargs = pytree.tree_map_only(torch.Tensor, torch.clone, args, kwargs)
        return func(*args, **kwargs)
    return clone_then_func


def schema_check(func, args, kwargs):
    with SchemaCheckMode():
        func(*args, **kwargs)


def check_compile(func, args, kwargs, backend, fullgraph, dynamic):
    expected = func(*args, **kwargs)
    compiled_func = torch.compile(func, backend=backend, fullgraph=fullgraph, dynamic=dynamic)
    result = compiled_func(*args, **kwargs)

    msg = (
        "Output of func(*args, **kwargs) with or without torch.compile is "
        "different (under backend={backend}, dynamic={dynamic}). Given that "
        "the other tests have passed, this is likely a bug within the "
        "torch.compile stack."
    )
    torch.testing.assert_close(expected, result, msg=msg)
