#include "dll.hpp"

#include <Python.h>

PyObject * mapFiles_mapFile( PyObject * self, PyObject * args )
{
    char const * from;
    char const * to;

    if ( !PyArg_ParseTuple( args, "ss", &from, &to ) )
    {
        PyErr_SetString( PyExc_Exception, "Invalid arguments - expected (string, string).");
        return NULL;
    }

    if ( addFileMapping( from, to ) )
        Py_RETURN_TRUE;
    Py_RETURN_FALSE;
}

PyObject * mapFiles_unmapFile( PyObject * self, PyObject * args )
{
    char const * from;

    if ( !PyArg_ParseTuple( args, "s", &from ) )
    {
        PyErr_SetString( PyExc_Exception, "Invalid arguments - expected (string).");
        return NULL;
    }

    if ( removeFileMapping( from ) )
        Py_RETURN_TRUE;
    Py_RETURN_FALSE;
}

PyObject * mapFiles_clearMappings( PyObject * self, PyObject * args )
{
    clearFileMappings();
    Py_RETURN_NONE;
}

static PyMethodDef mapFilesMethods[] = {
    { "mapFile"      , mapFiles_mapFile      , METH_VARARGS, "Add a file mapping for processes." },
    { "unmapFile"    , mapFiles_unmapFile    , METH_VARARGS, "Add a file mapping for processes." },
    { "clearMappings", mapFiles_clearMappings, METH_NOARGS , "Clear all file mappings." },
    { NULL, NULL, 0, NULL }
};

static PyModuleDef mapFiles = {
    PyModuleDef_HEAD_INIT,
    "map_files",
    "Extension which replaces CreateProcess() with a variant which allows mapping non-existing files to existing ones.",
    -1,
    mapFilesMethods, NULL, NULL, NULL, NULL
};

PyMODINIT_FUNC PyInit_map_files(void)
{
    DWORD replaced = hookWinAPI("Kernel32.dll", "CreateProcessA", (PROC)CreateProcessWithFSHookA);
    replaced = hookWinAPI("Kernel32.dll", "CreateProcessW", (PROC)CreateProcessWithFSHookW);
    return PyModule_Create(&mapFiles);
}

