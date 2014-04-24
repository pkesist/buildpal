#include "contentCache_.hpp"
#include "headerCache_.hpp"
#include "headerScanner_.hpp"

#include <Python.h>

#include <fstream>

#include <windows.h>

////////////////////////////////////////////////////////////////////////////////
//
// ----------------------
// PyPreprocessingContext
// ----------------------
//
////////////////////////////////////////////////////////////////////////////////

typedef struct {
    PyObject_HEAD
    PreprocessingContext * ppContext;
} PyPreprocessingContext;

void PyPreprocessingContext_dealloc( PyPreprocessingContext * self )
{
    delete self->ppContext;
    Py_TYPE(self)->tp_free( (PyObject *)self );
}

PyObject * PyPreprocessingContext_new( PyTypeObject * type, PyObject * args, PyObject * kwds )
{
    PyPreprocessingContext * self;
    self = (PyPreprocessingContext *)type->tp_alloc( type, 0 );
    return (PyObject *)self;
}

int PyPreprocessingContext_init( PyPreprocessingContext * self, PyObject * args, PyObject * kwds )
{
    delete self->ppContext;
    self->ppContext = new PreprocessingContext();
    return 0;
}

PyObject * PyPreprocessingContext_add_include_path( PyPreprocessingContext * self, PyObject * args, PyObject * kwds )
{
    static char * kwlist[] = { "path", "sysinclude", NULL };

    char const * path = 0;
    PyObject * sysInclude;

    if ( !PyArg_ParseTupleAndKeywords( args, kwds, "sO", kwlist, &path, &sysInclude ) )
        return NULL;

    if ( !self->ppContext )
        return NULL;

    self->ppContext->addIncludePath( path, PyObject_IsTrue( sysInclude ) != 0 );
    Py_RETURN_NONE;
}

PyObject * PyPreprocessingContext_add_ignored_header( PyPreprocessingContext * self, PyObject * args, PyObject * kwds )
{
    static char * kwlist[] = { "name", NULL };

    char const * name = 0;

    if ( !PyArg_ParseTupleAndKeywords( args, kwds, "s", kwlist, &name ) )
        return NULL;

    if ( !self->ppContext )
        return NULL;

    self->ppContext->addIgnoredHeader( name );
    Py_RETURN_NONE;
}

PyObject * PyPreprocessingContext_add_macro( PyPreprocessingContext * self, PyObject * args, PyObject * kwds )
{
    static char * kwlist[] = { "macro_name", "macro_value", NULL };

    char const * macroName = 0;
    char const * macroValue = 0;

    if ( !PyArg_ParseTupleAndKeywords( args, kwds, "ss", kwlist, &macroName, &macroValue ) )
        return NULL;

    if ( !self->ppContext )
        return NULL;

    self->ppContext->addMacro( macroName, macroValue );
    Py_RETURN_NONE;
}

PyMethodDef PyPreprocessingContext_methods[] =
{
    { "add_ignored_header", (PyCFunction)PyPreprocessingContext_add_ignored_header, METH_VARARGS | METH_KEYWORDS, "Add a search path." },
    { "add_include_path"  , (PyCFunction)PyPreprocessingContext_add_include_path, METH_VARARGS | METH_KEYWORDS, "Add a search path." },
    { "add_macro", (PyCFunction)PyPreprocessingContext_add_macro, METH_VARARGS | METH_KEYWORDS, "Add a macro." },
    {NULL}
};

PyTypeObject PyPreprocessingContextType = {
    PyVarObject_HEAD_INIT(NULL, 0)
    "PreprocessingContext",            /* tp_name */
    sizeof(PyPreprocessingContext),    /* tp_basicsize */
    0,                                 /* tp_itemsize */
    (destructor)PyPreprocessingContext_dealloc, /* tp_dealloc */
    0,                                 /* tp_print */
    0,                                 /* tp_getattr */
    0,                                 /* tp_setattr */
    0,                                 /* tp_reserved */
    0,                                 /* tp_repr */
    0,                                 /* tp_as_number */
    0,                                 /* tp_as_sequence */
    0,                                 /* tp_as_mapping */
    0,                                 /* tp_hash  */
    0,                                 /* tp_call */
    0,                                 /* tp_str */
    0,                                 /* tp_getattro */
    0,                                 /* tp_setattro */
    0,                                 /* tp_as_buffer */
    Py_TPFLAGS_DEFAULT,                /* tp_flags */
    "PreprocessingContext object",     /* tp_doc */
    0,                                 /* tp_traverse */
    0,                                 /* tp_clear */
    0,                                 /* tp_richcompare */
    0,                                 /* tp_weaklistoffset */
    0,                                 /* tp_iter */
    0,                                 /* tp_iternext */
    PyPreprocessingContext_methods,    /* tp_methods */
    0,                                 /* tp_members */
    0,                                 /* tp_getset */
    0,                                 /* tp_base */
    0,                                 /* tp_dict */
    0,                                 /* tp_descr_get */
    0,                                 /* tp_descr_set */
    0,                                 /* tp_dictoffset */
    (initproc)PyPreprocessingContext_init,      /* tp_init */
    0,                                 /* tp_alloc */
    PyPreprocessingContext_new,        /* tp_new */
};


////////////////////////////////////////////////////////////////////////////////
//
// -------
// PyCache
// -------
//
////////////////////////////////////////////////////////////////////////////////

typedef struct {
    PyObject_HEAD
    Cache * cache;
} PyCache;

void PyCache_dealloc( PyCache * self )
{
    delete self->cache;
    Py_TYPE(self)->tp_free( (PyObject *)self );
}

PyObject * PyCache_new( PyTypeObject * type, PyObject * args, PyObject * kwds )
{
    PyCache * self;
    self = (PyCache *)type->tp_alloc( type, 0 );
    return (PyObject *)self;
}

int PyCache_init( PyCache * self, PyObject * args, PyObject * kwds )
{
    delete self->cache;
    self->cache = new Cache();
    return 0;
}


PyObject * PyCache_dump( PyCache * self, PyObject * args, PyObject * kwds )
{
    static char * kwlist[] = { "filename", NULL };

    PyObject * filename = 0;

    if ( !PyArg_ParseTupleAndKeywords( args, kwds, "O", kwlist, &filename ) )
        return NULL;

    std::ofstream output( PyUnicode_AsUTF8( filename ) );
    self->cache->dump( output );
    Py_RETURN_NONE;
}

PyObject * PyCache_getStats( PyCache * self, PyObject * args, PyObject * kwds )
{
    assert( self->cache );
    PyObject * result = PyTuple_New( 2 );
    PyTuple_SET_ITEM( result, 0, PyLong_FromSize_t( self->cache->hits() ) );
    PyTuple_SET_ITEM( result, 1, PyLong_FromSize_t( self->cache->misses() ) );
    return result;
}


PyMethodDef PyCache_methods[] =
{
    {"dump", (PyCFunction)PyCache_dump, METH_VARARGS | METH_KEYWORDS, "Dump cache content to file."},
    {"get_stats", (PyCFunction)PyCache_getStats, METH_VARARGS | METH_KEYWORDS, "Get cache statistics."},
    {NULL}
};


PyTypeObject PyCacheType = {
    PyVarObject_HEAD_INIT(NULL, 0)
    "Cache",                    /* tp_name */
    sizeof(PyCache),            /* tp_basicsize */
    0,                          /* tp_itemsize */
    (destructor)PyCache_dealloc,/* tp_dealloc */
    0,                          /* tp_print */
    0,                          /* tp_getattr */
    0,                          /* tp_setattr */
    0,                          /* tp_reserved */
    0,                          /* tp_repr */
    0,                          /* tp_as_number */
    0,                          /* tp_as_sequence */
    0,                          /* tp_as_mapping */
    0,                          /* tp_hash  */
    0,                          /* tp_call */
    0,                          /* tp_str */
    0,                          /* tp_getattro */
    0,                          /* tp_setattro */
    0,                          /* tp_as_buffer */
    Py_TPFLAGS_DEFAULT,         /* tp_flags */
    "Cache object",             /* tp_doc */
    0,                          /* tp_traverse */
    0,                          /* tp_clear */
    0,                          /* tp_richcompare */
    0,                          /* tp_weaklistoffset */
    0,                          /* tp_iter */
    0,                          /* tp_iternext */
    PyCache_methods,            /* tp_methods */
    0,                          /* tp_members */
    0,                          /* tp_getset */
    0,                          /* tp_base */
    0,                          /* tp_dict */
    0,                          /* tp_descr_get */
    0,                          /* tp_descr_set */
    0,                          /* tp_dictoffset */
    (initproc)PyCache_init,     /* tp_init */
    0,                          /* tp_alloc */
    PyCache_new,                /* tp_new */
};


////////////////////////////////////////////////////////////////////////////////
//
// --------------
// PyPreprocessor
// --------------
//
////////////////////////////////////////////////////////////////////////////////

typedef struct {
    PyObject_HEAD
    Preprocessor * pp;
    PyObject * cache;
} PyPreprocessor;

void PyPreprocessor_dealloc( PyPreprocessor * self )
{
    Py_XDECREF( self->cache );
    delete self->pp;
    Py_TYPE(self)->tp_free( (PyObject *)self );
}

PyObject * PyPreprocessor_new( PyTypeObject * type, PyObject * args, PyObject * kwds )
{
    PyPreprocessor * self;
    self = (PyPreprocessor *)type->tp_alloc( type, 0 );
    return (PyObject *)self;
}

int PyPreprocessor_init( PyPreprocessor * self, PyObject * args, PyObject * kwds )
{
    static char * kwlist[] = { "cache", NULL };
    PyObject * pCache = 0;

    if ( !PyArg_ParseTupleAndKeywords( args, kwds, "O", kwlist, &pCache ) )
    {
        PyErr_SetString( PyExc_Exception, "Invalid cache parameter." );
        return -1;
    }

    if ( !pCache || ( pCache == Py_None ) )
    {
        self->pp = new Preprocessor( 0 );
        return 0;
    }

    if ( (PyTypeObject *)PyObject_Type( pCache ) != &PyCacheType )
    {
        PyErr_SetString( PyExc_Exception, "Invalid cache parameter." );
        return -1;
    }

    PyCache const * pyCache( reinterpret_cast<PyCache *>( pCache ) );
    assert( pyCache->cache );

    self->cache = pCache;
    Py_XINCREF( self->cache );
    self->pp = new Preprocessor( pyCache->cache );
    return 0;
}

PyObject * PyPreprocessor_scanHeaders( PyPreprocessor * self, PyObject * args, PyObject * kwds )
{
    static char * kwlist[] = { "pp_ctx", "filename", NULL };

    PyObject * pObject = 0;
    PyObject * filename = 0;

    assert( self->pp );

    if ( !PyArg_ParseTupleAndKeywords( args, kwds, "OO", kwlist, &pObject, &filename ) )
        return NULL;

    if ( !pObject || ( (PyTypeObject *)PyObject_Type( pObject ) != &PyPreprocessingContextType ) )
    {
        PyErr_SetString( PyExc_Exception, "Invalid preprocessing context parameter." );
        return NULL;
    }

    PyPreprocessingContext const * ppContext( reinterpret_cast<PyPreprocessingContext *>( pObject ) );

    if ( filename && !PyUnicode_Check( filename ) )
    {
        PyErr_SetString( PyExc_Exception, "Expected a string as 'filename' parameter." );
        return NULL;
    }

    Headers headers;
    PyThreadState * _save;
    try
    {
        Py_UNBLOCK_THREADS
        self->pp->scanHeaders( *ppContext->ppContext, PyUnicode_AsUTF8( filename ), headers );
    }
    catch ( std::runtime_error const & error )
    {
        Py_BLOCK_THREADS
        PyErr_SetString( PyExc_RuntimeError, error.what() );
        return NULL;
    }
    catch ( std::exception const & error )
    {
        Py_BLOCK_THREADS
        PyErr_SetString( PyExc_Exception, error.what() );
        return NULL;
    }
    catch ( ... )
    {
        Py_BLOCK_THREADS
        PyErr_SetString( PyExc_Exception, "Unhandled exception" );
        return NULL;
    }
    Py_BLOCK_THREADS
    
    // Group result by dir.
    struct HashDir
    {
        std::size_t operator()( Dir const & dir ) const
        {
            HashString hs;
            return hs( dir.get() );
        }
    };
    typedef std::unordered_map<Dir, PyObject *, HashDir> DirsAndHeaders;
    DirsAndHeaders dirsAndHeaders;
    for ( Header const & header : headers )
    {
        DirsAndHeaders::iterator iter( dirsAndHeaders.find( header.dir ) );
        if ( iter == dirsAndHeaders.end() )
            iter = dirsAndHeaders.insert( std::make_pair( header.dir, PyList_New( 0 ) ) ).first;
        PyObject * headerEntry = PyTuple_New( 4 );
        PyTuple_SET_ITEM( headerEntry, 0, PyUnicode_FromStringAndSize( header.name.get().data(), header.name.get().size() ) );

        PyObject * const isRelative( header.loc == HeaderLocation::relative ? Py_True : Py_False );
        Py_INCREF( isRelative );
        PyTuple_SET_ITEM( headerEntry, 1, isRelative );

        char * const data( const_cast<char *>( header.buffer->getBufferStart() ) );
        std::size_t const size( header.buffer->getBufferSize() );
        PyTuple_SET_ITEM( headerEntry, 2, PyMemoryView_FromMemory( data, size, PyBUF_READ ) );
        PyTuple_SET_ITEM( headerEntry, 3, PyLong_FromSize_t( header.checksum ) );
        PyList_Append( iter->second, headerEntry );
        Py_DECREF( headerEntry );
    }

    PyObject * resultTuple = PyTuple_New( dirsAndHeaders.size() );
    std::size_t index( 0 );
    for ( DirsAndHeaders::value_type const & dirAndHeaders : dirsAndHeaders )
    {
        PyObject * dirTuple = PyTuple_New( 2 );
        PyObject * dir = PyUnicode_FromStringAndSize( dirAndHeaders.first.get().data(), dirAndHeaders.first.get().size() );
        PyTuple_SET_ITEM( dirTuple, 0, dir );
        PyTuple_SET_ITEM( dirTuple, 1, dirAndHeaders.second );
        PyTuple_SET_ITEM( resultTuple, index++, dirTuple );
    }
    return resultTuple;
}

PyObject * PyPreprocessor_setMicrosoftExt( PyPreprocessor * self, PyObject * args, PyObject * kwds )
{
    static char * kwlist[] = { "value", NULL };

    PyObject * pVal = 0;

    if ( !PyArg_ParseTupleAndKeywords( args, kwds, "O", kwlist, &pVal ) )
    {
        PyErr_SetString( PyExc_Exception, "Failed to parse parameters." );
        return NULL;
    }

    self->pp->setMicrosoftExt( PyObject_IsTrue( pVal ) != 0 );

    Py_RETURN_NONE;
}

PyObject * PyPreprocessor_setMicrosoftMode( PyPreprocessor * self, PyObject * args, PyObject * kwds )
{
    static char * kwlist[] = { "value", NULL };

    PyObject * pVal = 0;

    if ( !PyArg_ParseTupleAndKeywords( args, kwds, "O", kwlist, &pVal ) )
    {
        PyErr_SetString( PyExc_Exception, "Failed to parse parameters." );
        return NULL;
    }

    self->pp->setMicrosoftMode( PyObject_IsTrue( pVal ) != 0 );

    Py_RETURN_NONE;
}

PyMethodDef PyPreprocessor_methods[] =
{
    {"scan_headers", (PyCFunction)PyPreprocessor_scanHeaders     , METH_VARARGS | METH_KEYWORDS, "Retrieve a list of include files."},
    {"set_ms_ext"  , (PyCFunction)PyPreprocessor_setMicrosoftExt , METH_VARARGS | METH_KEYWORDS, "Set MS extension mode."},
    {"set_ms_mode" , (PyCFunction)PyPreprocessor_setMicrosoftMode, METH_VARARGS | METH_KEYWORDS, "Set MS mode."},
    {NULL}
};

PyTypeObject PyPreprocessorType = {
    PyVarObject_HEAD_INIT(NULL, 0)
    "Preprocessor",                     /* tp_name */
    sizeof(PyPreprocessor),             /* tp_basicsize */
    0,                                  /* tp_itemsize */
    (destructor)PyPreprocessor_dealloc, /* tp_dealloc */
    0,                                  /* tp_print */
    0,                                  /* tp_getattr */
    0,                                  /* tp_setattr */
    0,                                  /* tp_reserved */
    0,                                  /* tp_repr */
    0,                                  /* tp_as_number */
    0,                                  /* tp_as_sequence */
    0,                                  /* tp_as_mapping */
    0,                                  /* tp_hash  */
    0,                                  /* tp_call */
    0,                                  /* tp_str */
    0,                                  /* tp_getattro */
    0,                                  /* tp_setattro */
    0,                                  /* tp_as_buffer */
    Py_TPFLAGS_DEFAULT,                 /* tp_flags */
    "Preprocessor object",              /* tp_doc */
    0,                                  /* tp_traverse */
    0,                                  /* tp_clear */
    0,                                  /* tp_richcompare */
    0,                                  /* tp_weaklistoffset */
    0,                                  /* tp_iter */
    0,                                  /* tp_iternext */
    PyPreprocessor_methods,             /* tp_methods */
    0,                                  /* tp_members */
    0,                                  /* tp_getset */
    0,                                  /* tp_base */
    0,                                  /* tp_dict */
    0,                                  /* tp_descr_get */
    0,                                  /* tp_descr_set */
    0,                                  /* tp_dictoffset */
    (initproc)PyPreprocessor_init,      /* tp_init */
    0,                                  /* tp_alloc */
    PyPreprocessor_new,                 /* tp_new */
};


PyObject * Preprocessing_clearContentCache( PyObject * something, PyObject * somethingElse )
{
    ContentCache::singleton().clear();
    Py_RETURN_NONE;
}

static PyMethodDef preprocessingMethods[] = {
    {"clear_content_cache", Preprocessing_clearContentCache, METH_NOARGS, "Execute a shell command."},
    {NULL, NULL, 0, NULL}
};

static PyModuleDef preprocessingModule = {
    PyModuleDef_HEAD_INIT,
    "preprocessor",
    "Module for scanning and collecting header files from C source.",
    -1,
    preprocessingMethods, NULL, NULL, NULL, NULL
};

PyMODINIT_FUNC PyInit_preprocessing(void)
{
    PyObject * m;

    if ( PyType_Ready( &PyPreprocessingContextType ) < 0 )
        return NULL;
    if ( PyType_Ready( &PyCacheType ) < 0 )
        return NULL;
    if ( PyType_Ready( &PyPreprocessorType ) < 0 )
        return NULL;
    m = PyModule_Create( &preprocessingModule );
    if ( m == NULL )
        return NULL;

    Py_INCREF( &PyPreprocessingContextType );
    PyModule_AddObject( m, "PreprocessingContext", (PyObject *)&PyPreprocessingContextType );
    Py_INCREF( &PyCacheType );
    PyModule_AddObject( m, "Cache", (PyObject *)&PyCacheType );
    Py_INCREF( &PyPreprocessorType );
    PyModule_AddObject( m, "Preprocessor", (PyObject *)&PyPreprocessorType );
    return m;
}