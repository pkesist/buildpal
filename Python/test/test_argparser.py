import pytest

from buildpal.manager.compilers.msvc import MSVCCompiler

@pytest.mark.parametrize(("option"), (
    'AI', 'bigobj',
    'C', 'c', 'clr',
    'doc',
    'E','EH', 'EP', 'errorReport',
    'F', 'favor', 'FA', 'Fa', 'FC',
    'Fd', 'Fe', 'Fi', 'Fm',
    'Fo', 'fp', 'Fp', 'FR', 'Fr',
    'FS', 'Fx', 'GA',
    'Gd', 'Ge', 'GF', 'GH', 'Gh',
    'GL', 'Gm', 'GR', 'Gr', 'GS',
    'Gs', 'GT', 'GX',
    'Gy', 'GZ', 'Gz',
    'H', 'HELP', 'homeparams', 'hotpatch',
    'J',
    'kernel',
    'LD', 'LDd', 'link', 'LN',
    'MD', 'MDd', 'MP', 'MT', 'MTd',
    'nologo',
    'openmp',
    'P',
    'Qfast_transcendentals', 'QIfist',
    'Qimprecise_fwaits', 'Qpar',
    'RTC',
    'sdl', 'showIncludes',
    'TC', 'TP',
    'u',
    'V', 'vd', 'vmb', 'vmg',
    'vmm', 'vms', 'vmv', 'volatile',
    'w', 'W0', 'W1', 'W2', 'W3', 'W4',
    'Wall', 'WL','Wp64',
    'X',
    'Y-', 'Yc', 'Yd', 'Yl', 'Yu',
    'Z7', 'Za', 'Ze','Zg',
    'ZI', 'Zi', 'Zl', 'Zm','Zp',
    'Zs', 'ZW',
))
def test_standalone_option_valid(option):
    options = MSVCCompiler.parse_options(['/{}'.format(option)])
    assert len(options.option_names) == 1
    assert option in options.option_names

@pytest.mark.parametrize(("option"), (
    'arch:', 'D', 'FI', 'FU', 'I', 'O', 'Qvec-report', 'Tc', 'Tp', 'U', 'Zc:', 
))
def test_option_with_arg_valid(option):
    options = MSVCCompiler.parse_options(['/{}{}'.format(option, 'teststring')])
    assert len(options.option_names) == 1
    assert option in options.option_names
    assert len(options.option_values) == 1
    assert len(options.option_values[0]) == 1
    assert 'teststring' in options.option_values[0]

# These are not recognized by Clang. Add a test to notice when they are.
@pytest.mark.parametrize(("option"), (
    'analyze', 'cgthreads', 'Gv', 'Gw', 'Qsafe_fp_loads'
))
def test_unrecognized_arg(option):
    options = MSVCCompiler.parse_options(['/{}{}'.format(option, 'teststring')])
    assert len(options.option_names) == 1
    # If not recognized it is considered an input file.
    assert '<input>' in options.option_names
    
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
    assert set(x[0] for x in options.source_files()) == expected

@pytest.mark.parametrize(("input", "expected"), (
    (['/D_ASDF', '/D_FDSA'], {'_ASDF', '_FDSA'}),
))
def test_macro_defs(input, expected):
    options = MSVCCompiler.parse_options(input)
    assert set(options.defines()) == expected

@pytest.mark.parametrize(("input", "expected"), (
    (['x', 'y', 'z'], []),
    (['x', 'y', 'z', '/link'], ['/link']),
    (['x', 'y', 'z', '/link', 'a', 'b'], ['/link', 'a', 'b']),
))
def test_link_opts(input, expected):
    options = MSVCCompiler.parse_options(input)
    assert list(options.link_options()) == expected

