#include "mapFiles.hpp"

#include "../Common/createProcess.hpp"
#include "../Common/createProcessMacros.hpp"

#include <memory>

#include <Python.h>

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

namespace
{
    struct CPData
    {
        DWORD const * fileMaps;
        DWORD fileMapCount;
    };

    BOOL WINAPI createProcessHelper( CREATE_PROCESS_PARAMSW, void * vpData )
    {
        CPData const * data = reinterpret_cast<CPData *>( vpData );
        return createProcessWithMappingW(
            CREATE_PROCESS_ARGS,
            data->fileMaps,
            data->fileMapCount
        );
    }
}

PyObject * PyFileMap_createProcess( PyFileMap * self, PyObject * args )
{
    CPData cpData = { &self->fileMap, 1 };
    return pythonCreateProcess( args, &createProcessHelper, &cpData );
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
    CPData cpData = { ptr.get(), size };
    return pythonCreateProcess( args, &createProcessHelper, &cpData );
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
