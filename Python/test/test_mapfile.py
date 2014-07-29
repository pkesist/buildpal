import os
import map_files
import subprocess

def test_fs_hook_file(tmpdir):
    f = tmpdir.join("lol.txt")
    f.write('content')
    does_not_exist = 'c:\\i_do_not_exist\\a_little_file.txt'
    map_files.map_file(does_not_exist, str(f))
    assert not os.path.exists(does_not_exist)
    map_files.enable()
    assert os.path.exists(does_not_exist)
    map_files.disable()
    assert not os.path.exists(does_not_exist)

def test_compile_nonexisting_file(tmpdir, vcenv_and_cl):
    f = tmpdir.join("lol.txt")
    f.write('')
    does_not_exist = 'c:\\i_do_not_exist\\a_little_file.cpp'
    map_files.map_file(does_not_exist, str(f))
    map_files.enable()
    vcenv, cl = vcenv_and_cl
    assert subprocess.call([cl, '/c', does_not_exist], env=vcenv, cwd=str(tmpdir)) == 0


