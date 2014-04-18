#include "mapFilesInject.hpp"

#include <Python.h>

#if defined(MS_WIN32) && !defined(MS_WIN64)
#define HANDLE_TO_PYNUM(handle) \
    PyLong_FromUnsignedLong((unsigned long) handle)
#define PYNUM_TO_HANDLE(obj) ((HANDLE)PyLong_AsUnsignedLong(obj))
#define F_POINTER "k"
#define T_POINTER T_ULONG
#else
#define HANDLE_TO_PYNUM(handle) \
    PyLong_FromUnsignedLongLong((unsigned long long) handle)
#define PYNUM_TO_HANDLE(obj) ((HANDLE)PyLong_AsUnsignedLongLong(obj))
#define F_POINTER "K"
#define T_POINTER T_ULONGLONG
#endif

static unsigned long
getulong(PyObject* obj, char* name)
{
    PyObject* value;
    unsigned long ret;

    value = PyObject_GetAttrString(obj, name);
    if (! value) {
        PyErr_Clear(); /* FIXME: propagate error? */
        return 0;
    }
    ret = PyLong_AsUnsignedLong(value);
    Py_DECREF(value);
    return ret;
}

static HANDLE
gethandle(PyObject* obj, char* name)
{
    PyObject* value;
    HANDLE ret;

    value = PyObject_GetAttrString(obj, name);
    if (! value) {
        PyErr_Clear(); /* FIXME: propagate error? */
        return NULL;
    }
    if (value == Py_None)
        ret = NULL;
    else
        ret = PYNUM_TO_HANDLE(value);
    Py_DECREF(value);
    return ret;
}

static PyObject*
getenvironment(PyObject* environment)
{
    Py_ssize_t i, envsize, totalsize;
    Py_UCS4 *buffer = NULL, *p, *end;
    PyObject *keys, *values, *res;

    /* convert environment dictionary to windows enviroment string */
    if (! PyMapping_Check(environment)) {
        PyErr_SetString(
            PyExc_TypeError, "environment must be dictionary or None");
        return NULL;
    }

    envsize = PyMapping_Length(environment);

    keys = PyMapping_Keys(environment);
    values = PyMapping_Values(environment);
    if (!keys || !values)
        goto error;

    totalsize = 1; /* trailing null character */
    for (i = 0; i < envsize; i++) {
        PyObject* key = PyList_GET_ITEM(keys, i);
        PyObject* value = PyList_GET_ITEM(values, i);

        if (! PyUnicode_Check(key) || ! PyUnicode_Check(value)) {
            PyErr_SetString(PyExc_TypeError,
                "environment can only contain strings");
            goto error;
        }
        totalsize += PyUnicode_GET_LENGTH(key) + 1;    /* +1 for '=' */
        totalsize += PyUnicode_GET_LENGTH(value) + 1;  /* +1 for '\0' */
    }

    buffer = static_cast<Py_UCS4 *>(PyMem_Malloc(totalsize * sizeof(Py_UCS4)));
    if (! buffer)
        goto error;
    p = buffer;
    end = buffer + totalsize;

    for (i = 0; i < envsize; i++) {
        PyObject* key = PyList_GET_ITEM(keys, i);
        PyObject* value = PyList_GET_ITEM(values, i);
        if (!PyUnicode_AsUCS4(key, p, end - p, 0))
            goto error;
        p += PyUnicode_GET_LENGTH(key);
        *p++ = '=';
        if (!PyUnicode_AsUCS4(value, p, end - p, 0))
            goto error;
        p += PyUnicode_GET_LENGTH(value);
        *p++ = '\0';
    }

    /* add trailing null byte */
    *p++ = '\0';
    assert(p == end);

    Py_XDECREF(keys);
    Py_XDECREF(values);

    res = PyUnicode_FromKindAndData(PyUnicode_4BYTE_KIND, buffer, p - buffer);
    PyMem_Free(buffer);
    return res;

 error:
    PyMem_Free(buffer);
    Py_XDECREF(keys);
    Py_XDECREF(values);
    return NULL;
}

PyObject * mapFiles_createProcess( PyObject* self, PyObject* args )
{
    BOOL result;
    PROCESS_INFORMATION pi;
    STARTUPINFOW si;
    PyObject* environment;
    wchar_t *wenvironment;

    PyObject* file_mapping;
    wchar_t* application_name;
    wchar_t* command_line;
    PyObject* process_attributes; /* ignored */
    PyObject* thread_attributes; /* ignored */
    BOOL inherit_handles;
    DWORD creation_flags;
    PyObject* env_mapping;
    wchar_t* current_directory;
    PyObject* startup_info;

    if (! PyArg_ParseTuple(args, "OZZOOikOZO:mapFiles_createProcess",
                           &file_mapping,
                           &application_name,
                           &command_line,
                           &process_attributes,
                           &thread_attributes,
                           &inherit_handles,
                           &creation_flags,
                           &env_mapping,
                           &current_directory,
                           &startup_info))
        return NULL;

    ZeroMemory(&si, sizeof(si));
    si.cb = sizeof(si);

    /* note: we only support a small subset of all SI attributes */
    si.dwFlags = getulong(startup_info, "dwFlags");
    si.wShowWindow = (WORD)getulong(startup_info, "wShowWindow");
    si.hStdInput = gethandle(startup_info, "hStdInput");
    si.hStdOutput = gethandle(startup_info, "hStdOutput");
    si.hStdError = gethandle(startup_info, "hStdError");
    if (PyErr_Occurred())
        return NULL;

    if (env_mapping != Py_None) {
        environment = getenvironment(env_mapping);
        if (! environment)
            return NULL;
        wenvironment = PyUnicode_AsUnicode(environment);
        if (wenvironment == NULL)
        {
            Py_XDECREF(environment);
            return NULL;
        }
    }
    else {
        environment = NULL;
        wenvironment = NULL;
    }

    DWORD fileMap = createFileMap();
    {
        PyObject * key;
        PyObject * value;
        Py_ssize_t pos = 0;

        while ( PyDict_Next( file_mapping, &pos, &key, &value ) )
        {
            mapFileW( fileMap, PyUnicode_AsUnicode( key ), PyUnicode_AsUnicode( value ) );
        }
    }
    Py_BEGIN_ALLOW_THREADS
    result = createProcessWithMappingW(application_name,
                           command_line,
                           NULL,
                           NULL,
                           inherit_handles,
                           creation_flags | CREATE_UNICODE_ENVIRONMENT,
                           wenvironment,
                           current_directory,
                           &si,
                           &pi,
                           fileMap);
    Py_END_ALLOW_THREADS

    Py_XDECREF(environment);

    if (! result)
        return PyErr_SetFromWindowsErr(GetLastError());

    return Py_BuildValue("NNkk",
                         HANDLE_TO_PYNUM(pi.hProcess),
                         HANDLE_TO_PYNUM(pi.hThread),
                         pi.dwProcessId,
                         pi.dwThreadId);
}


PyObject * mapFiles_mapFile( PyObject* self, PyObject* args )
{
    PyObject * virtualFile;
    PyObject * file;

    if ( !PyArg_ParseTuple( args, "OO:mapFiles_mapFile", &virtualFile, &file ) )
        return NULL;
    if ( !PyUnicode_Check( virtualFile ) )
        return NULL;
    if ( !PyUnicode_Check( file ) )
        return NULL;
    if ( mapFileGlobalW( PyUnicode_AsUnicode( virtualFile ), PyUnicode_AsUnicode( file ) ) )
        Py_RETURN_TRUE;
    Py_RETURN_FALSE;
}

PyObject * mapFiles_unmapFile( PyObject* self, PyObject* args )
{
    PyObject * virtualFile;

    if ( !PyArg_ParseTuple( args, "O:mapFiles_unmapFile", &virtualFile ) )
        return NULL;
    if ( !PyUnicode_Check( virtualFile ) )
        return NULL;
    if ( unmapFileGlobalW( PyUnicode_AsUnicode( virtualFile ) ) )
        Py_RETURN_TRUE;
    Py_RETURN_FALSE;
}

PyObject * mapFiles_enable( PyObject * self )
{
    hookWinAPIs();
    Py_RETURN_NONE;
}

PyObject * mapFiles_disable( PyObject * self )
{
    unhookWinAPIs();
    Py_RETURN_NONE;
}


static PyMethodDef mapFilesMethods[] = {
    { "createProcess", mapFiles_createProcess, METH_VARARGS, "Add a file mapping for processes." },
    { "mapFile"      , mapFiles_mapFile      , METH_VARARGS, "Map a file to another one." },
    { "unmapFile"    , mapFiles_unmapFile    , METH_VARARGS, "Unmap a file." },
    { "enable"       , (PyCFunction)mapFiles_enable       , METH_NOARGS , "Enable hooks." },
    { "disable"      , (PyCFunction)mapFiles_disable      , METH_NOARGS , "Disable hooks." },
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
    return PyModule_Create( &mapFiles );
}
