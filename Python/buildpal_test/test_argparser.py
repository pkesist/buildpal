import pytest

from buildpal_manager.compilers.msvc import MSVCCompiler

@pytest.mark.parametrize(("input", "expected"), (
    (['lib.lib'], set()),
    (['test.c'], {'test.c'}),
    (['test.cc'], {'test.cc'}),
    (['test.cpp'], {'test.cpp'}),
    (['test.cxx'], {'test.cxx'}),
    (['/Tctest.c'], {'test.c'}),
    (['/Tptest.c'], {'test.c'}),
    (['/Tclib.lib'], {'lib.lib'}),
    (['/Tplib.lib'], {'lib.lib'}),
    (['lib.lib', '/TC'], {'lib.lib'}),
    (['lib.lib', '/TP'], {'lib.lib'}),
    (['x.y', 'x.c'], {'x.c'}),
    (['x.y', 'x.cx'], set()),
    (['x.y', 'x.cp'], set()),
    (['x.y', 'x.ccc'], set()),
    (['x.y', 'x'], set()),
    (['/TC', '/FD'], set()),
))
def test_input_files(input, expected):
    options = MSVCCompiler.parse_options(input)
    assert set(options.input_files()) == expected


