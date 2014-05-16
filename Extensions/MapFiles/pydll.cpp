#include "mapFilesInject.hpp"

#include <memory>

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
    { "mapFile"      , mapFiles_mapFile             , METH_VARARGS, "Map a file to another one." },
    { "unmapFile"    , mapFiles_unmapFile           , METH_VARARGS, "Unmap a file." },
    { "enable"       , (PyCFunction)mapFiles_enable , METH_NOARGS , "Enable hooks." },
    { "disable"      , (PyCFunction)mapFiles_disable, METH_NOARGS , "Disable hooks." },
    { NULL, NULL, 0, NULL }
};

static PyModuleDef mapFiles = {
    PyModuleDef_HEAD_INIT,
    "map_files",
    "Extension which replaces CreateProcess() with a variant which allows mapping non-existing files to existing ones.",
    -1,
    mapFilesMethods, NULL, NULL, NULL, NULL
};

typedef struct {
    PyObject_HEAD
    DWORD fileMap;
} PyFileMap;

void PyFileMap_dealloc( PyFileMap * self )
{
    destroyFileMap( self->fileMap );
    Py_TYPE(self)->tp_free( (PyObject *)self );
}

PyObject * PyFileMap_new( PyTypeObject * type, PyObject * args, PyObject * kwds )
{
    PyFileMap * self;
    self = (PyFileMap *)type->tp_alloc( type, 0 );
    return (PyObject *)self;
}

int PyFileMap_init( PyFileMap * self, PyObject * args, PyObject * kwds )
{
    destroyFileMap( self->fileMap );
    self->fileMap = createFileMap();
    return 0;
}

PyObject * PyFileMap_addMapping( PyFileMap * self, PyObject * args, PyObject * kwds )
{
    static char * kwlist[] = { "virtual_path", "real_path", NULL };

    PyObject * virtualFile = 0;
    PyObject * realFile = 0;

    if ( !PyArg_ParseTupleAndKeywords( args, kwds, "UU", kwlist, &virtualFile, &realFile ) )
        return NULL;

    if ( !self->fileMap )
        return NULL;

    BOOL result = mapFileW( self->fileMap, PyUnicode_AS_UNICODE( virtualFile ), PyUnicode_AS_UNICODE( realFile ) );
    if ( result )
        Py_RETURN_TRUE;
    Py_RETURN_FALSE;
}

PyObject * createProcessWithFileMaps( DWORD const * fileMaps, DWORD fileMapCount, PyObject * args )
{
    BOOL result;
    PROCESS_INFORMATION pi;
    STARTUPINFOW si;
    PyObject* environment;
    wchar_t *wenvironment;

    wchar_t* application_name;
    wchar_t* command_line;
    PyObject* process_attributes; /* ignored */
    PyObject* thread_attributes; /* ignored */
    BOOL inherit_handles;
    DWORD creation_flags;
    PyObject* env_mapping;
    wchar_t* current_directory;
    PyObject* startup_info;

    if (! PyArg_ParseTuple(args, "ZZOOikOZO:mapFiles_createProcess",
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
                           fileMaps,
                           fileMapCount);
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

PyObject * PyFileMap_createProcess( PyFileMap * self, PyObject * args )
{
    return createProcessWithFileMaps( &self->fileMap, 1, args );
}

PyMethodDef PyFileMap_methods[] =
{
    { "map_file"      , (PyCFunction)PyFileMap_addMapping, METH_VARARGS | METH_KEYWORDS, "Map a virtual file to real file." },
    { "create_process", (PyCFunction)PyFileMap_createProcess, METH_VARARGS, "Create a process with virtual files." },
    {NULL}
};

PyTypeObject PyFileMapType = {
    PyVarObject_HEAD_INIT(NULL, 0)
    "PyFileMap",                   /* tp_name */
    sizeof(PyFileMap),             /* tp_basicsize */
    0,                             /* tp_itemsize */
    (destructor)PyFileMap_dealloc, /* tp_dealloc */
    0,                             /* tp_print */
    0,                             /* tp_getattr */
    0,                             /* tp_setattr */
    0,                             /* tp_reserved */
    0,                             /* tp_repr */
    0,                             /* tp_as_number */
    0,                             /* tp_as_sequence */
    0,                             /* tp_as_mapping */
    0,                             /* tp_hash  */
    0,                             /* tp_call */
    0,                             /* tp_str */
    0,                             /* tp_getattro */
    0,                             /* tp_setattro */
    0,                             /* tp_as_buffer */
    Py_TPFLAGS_DEFAULT,            /* tp_flags */
    "PyFileMap object",            /* tp_doc */
    0,                             /* tp_traverse */
    0,                             /* tp_clear */
    0,                             /* tp_richcompare */
    0,                             /* tp_weaklistoffset */
    0,                             /* tp_iter */
    0,                             /* tp_iternext */
    PyFileMap_methods,             /* tp_methods */
    0,                             /* tp_members */
    0,                             /* tp_getset */
    0,                             /* tp_base */
    0,                             /* tp_dict */
    0,                             /* tp_descr_get */
    0,                             /* tp_descr_set */
    0,                             /* tp_dictoffset */
    (initproc)PyFileMap_init,      /* tp_init */
    0,                             /* tp_alloc */
    PyFileMap_new,                 /* tp_new */
};

typedef struct {
    PyObject_HEAD
    PyObject * fileMapTuple;
} PyFileMapComposition;

void PyFileMapComposition_dealloc( PyFileMapComposition * self )
{
    Py_DECREF( self->fileMapTuple );
    Py_TYPE(self)->tp_free( (PyObject *)self );
}

PyObject * PyFileMapComposition_new( PyTypeObject * type, PyObject * args, PyObject * kwds )
{
    PyFileMap * self;
    self = (PyFileMap *)type->tp_alloc( type, 0 );
    return (PyObject *)self;
}

int PyFileMapComposition_init( PyFileMapComposition * self, PyObject * args, PyObject * kwds )
{
    Py_ssize_t const size( PyTuple_GET_SIZE( args ) );
    for ( Py_ssize_t index( 0 ); index < size; ++index )
    {
        PyObject * const obj = PyTuple_GET_ITEM( args, index );
        if ( (PyTypeObject *)PyObject_Type( obj ) != &PyFileMapType )
            return NULL;
    }
    // Now that we are sure that arguments are valid, increase refcounts.
    Py_XINCREF( args );
    self->fileMapTuple = args;
    return 0;
}

PyObject * PyFileMapComposition_createProcess( PyFileMapComposition * self, PyObject * args )
{
    Py_ssize_t const size( PyTuple_GET_SIZE( self->fileMapTuple ) );
    std::unique_ptr<DWORD []> ptr( new DWORD[ size ] );
    for ( Py_ssize_t index( 0 ); index < size; ++index )
    {
        PyFileMap * fileMap = (PyFileMap *)PyTuple_GET_ITEM( self->fileMapTuple, index );
        ptr[ index ] = fileMap->fileMap;
    }
    return createProcessWithFileMaps( ptr.get(), size, args );
}

PyMethodDef PyFileMapComposition_methods[] =
{
    { "create_process", (PyCFunction)PyFileMapComposition_createProcess, METH_VARARGS, "Create a process with virtual files." },
    {NULL}
};

PyTypeObject PyFileMapCompositionType = {
    PyVarObject_HEAD_INIT(NULL, 0)
    "PyFileMap",                              /* tp_name */
    sizeof(PyFileMap),                        /* tp_basicsize */
    0,                                        /* tp_itemsize */
    (destructor)PyFileMapComposition_dealloc, /* tp_dealloc */
    0,                                        /* tp_print */
    0,                                        /* tp_getattr */
    0,                                        /* tp_setattr */
    0,                                        /* tp_reserved */
    0,                                        /* tp_repr */
    0,                                        /* tp_as_number */
    0,                                        /* tp_as_sequence */
    0,                                        /* tp_as_mapping */
    0,                                        /* tp_hash  */
    0,                                        /* tp_call */
    0,                                        /* tp_str */
    0,                                        /* tp_getattro */
    0,                                        /* tp_setattro */
    0,                                        /* tp_as_buffer */
    Py_TPFLAGS_DEFAULT,                       /* tp_flags */
    "PyFileMapComposition object",            /* tp_doc */
    0,                                        /* tp_traverse */
    0,                                        /* tp_clear */
    0,                                        /* tp_richcompare */
    0,                                        /* tp_weaklistoffset */
    0,                                        /* tp_iter */
    0,                                        /* tp_iternext */
    PyFileMapComposition_methods,             /* tp_methods */
    0,                                        /* tp_members */
    0,                                        /* tp_getset */
    0,                                        /* tp_base */
    0,                                        /* tp_dict */
    0,                                        /* tp_descr_get */
    0,                                        /* tp_descr_set */
    0,                                        /* tp_dictoffset */
    (initproc)PyFileMapComposition_init,      /* tp_init */
    0,                                        /* tp_alloc */
    PyFileMapComposition_new,                 /* tp_new */
};

PyMODINIT_FUNC PyInit_map_files(void)
{
    PyObject * m = PyModule_Create( &mapFiles );

    if ( PyType_Ready( &PyFileMapType ) < 0 )
        return NULL;

    if ( PyType_Ready( &PyFileMapCompositionType ) < 0 )
    return NULL;

    Py_INCREF( &PyFileMapType );
    Py_INCREF( &PyFileMapCompositionType );

    PyModule_AddObject( m, "FileMap", (PyObject *)&PyFileMapType );
    PyModule_AddObject( m, "FileMapComposition", (PyObject *)&PyFileMapCompositionType );
    return m;
}
