#include "headerScanner_.hpp"

#include <Python.h>


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
    PyObject * sysInclude = Py_False;

    if ( !PyArg_ParseTupleAndKeywords( args, kwds, "s|O", kwlist, &path, &sysInclude ) )
        return NULL;

    if ( !self->ppContext )
        return NULL;

    self->ppContext->addIncludePath( path, PyObject_IsTrue( sysInclude ) );
    Py_RETURN_NONE;
}

PyObject * PyPreprocessingContext_add_macro( PyPreprocessingContext * self, PyObject * args, PyObject * kwds )
{
    static char * kwlist[] = { "macro_name", "macro_value", NULL };

    char const * macroName = 0;
    char const * macroValue = "";

    if ( !PyArg_ParseTupleAndKeywords( args, kwds, "s|s", kwlist, &macroName, &macroValue ) )
        return NULL;

    if ( !self->ppContext )
        return NULL;

    self->ppContext->addMacro( macroName, macroValue );
    Py_RETURN_NONE;
}

PyMethodDef PyPreprocessingContext_methods[] =
{
    { "add_include_path", (PyCFunction)PyPreprocessingContext_add_include_path, METH_VARARGS | METH_KEYWORDS, "Add a search path." },
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
// --------------
// PyPreprocessor
// --------------
//
////////////////////////////////////////////////////////////////////////////////

typedef struct {
    PyObject_HEAD
    Preprocessor * pp;
} PyPreprocessor;

void PyPreprocessor_dealloc( PyPreprocessor * self )
{
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
    delete self->pp;
    self->pp = new Preprocessor();
    return 0;
}

PyObject * PyPreprocessor_scanHeaders( PyPreprocessor * self, PyObject * args, PyObject * kwds )
{
    static char * kwlist[] = { "pp_ctx", "filename", "headers_to_skip", NULL };

    PyObject * pObject = 0;
    char const * filename = 0;
    PyObject * headersToSkipList = 0;

    assert( self->pp );

    if ( !PyArg_ParseTupleAndKeywords( args, kwds, "Os|O", kwlist, &pObject, &filename, &headersToSkipList ) )
        return NULL;

    if ( !pObject || ( (PyTypeObject *)PyObject_Type( pObject ) != &PyPreprocessingContextType ) )
    {
        PyErr_SetString( PyExc_Exception, "Invalid preprocessing context parameter." );
        return NULL;
    }

    Preprocessor::HeaderList headersToSkip;
    if ( headersToSkipList )
    {
        if ( !PyList_Check( headersToSkipList ) )
        {
            PyErr_SetString( PyExc_Exception, "headers_to_skip parameter must be a list of strings." );
            return NULL;
        }
        Py_ssize_t const size( PyList_Size( headersToSkipList ) );
        for ( Py_ssize_t iter( 0 ); iter < size; ++iter )
        {
            PyObject * entry( PyList_GET_ITEM( headersToSkipList, iter ) );
            if ( !PyUnicode_Check( entry ) )
            {
                PyErr_SetString( PyExc_Exception, "headers_to_skip parameter must be a list of strings." );
                return NULL;
            }
            headersToSkip.insert( PyUnicode_AsUTF8( entry ) );
        }
    }

    PyPreprocessingContext const * ppContext( reinterpret_cast<PyPreprocessingContext *>( pObject ) );
    Preprocessor::HeaderRefs const headers = self->pp->scanHeaders( *ppContext->ppContext, filename, headersToSkip );

    PyObject * result = PyTuple_New( headers.size() );
    unsigned int index( 0 );
    for ( Preprocessor::HeaderRefs::const_iterator iter = headers.begin(); iter != headers.end(); ++iter )
    {
        PyObject * tuple = PyTuple_New( 2 );
        PyObject * first = PyUnicode_FromStringAndSize( iter->first.data(), iter->first.size() );
        PyObject * second = PyUnicode_FromStringAndSize( iter->second.data(), iter->second.size() );
        PyTuple_SET_ITEM( tuple, 0, first );
        PyTuple_SET_ITEM( tuple, 1, second );

        PyTuple_SET_ITEM( result, index++, tuple );
    }
    return result;
}

PyObject * PyPreprocessor_preprocess( PyPreprocessor * self, PyObject * args, PyObject * kwds )
{
    static char * kwlist[] = { "pp_ctx", "filename", NULL };

    PyObject * pObject = 0;
    char const * filename = 0;


    assert( self->pp );
    if ( !PyArg_ParseTupleAndKeywords( args, kwds, "Os", kwlist, &pObject, &filename ) )
    {
        PyErr_SetString( PyExc_Exception, "Failed to parse parameters." );
        return NULL;
    }

    if ( !pObject || ( (PyTypeObject *)PyObject_Type( pObject ) != &PyPreprocessingContextType ) )
    {
        PyErr_SetString( PyExc_Exception, "Invalid preprocessor object." );
        return NULL;
    }

    PyPreprocessingContext const * ppContext( reinterpret_cast<PyPreprocessingContext *>( pObject ) );
    std::string output;
    output.reserve( 100 * 1024 );
    self->pp->preprocess( *ppContext->ppContext, filename, output );

    return PyBytes_FromStringAndSize( output.data(), output.size() );
}

PyObject * PyPreprocessor_setMicrosoftExt( PyPreprocessor * self, PyObject * args, PyObject * kwds )
{
    static char * kwlist[] = { "value", NULL };

    PyObject * pVal = 0;

    if ( !PyArg_ParseTupleAndKeywords( args, kwds, "O:bool", kwlist, &pVal ) )
    {
        PyErr_SetString( PyExc_Exception, "Failed to parse parameters." );
        return NULL;
    }

    self->pp->setMicrosoftExt( PyObject_IsTrue( pVal ) );

    Py_RETURN_NONE;
}

PyObject * PyPreprocessor_setExceptions( PyPreprocessor * self, PyObject * args, PyObject * kwds )
{
    static char * kwlist[] = { "value", NULL };

    PyObject * pVal = 0;

    if ( !PyArg_ParseTupleAndKeywords( args, kwds, "O:bool", kwlist, &pVal ) )
    {
        PyErr_SetString( PyExc_Exception, "Failed to parse parameters." );
        return NULL;
    }

    self->pp->setExceptions( PyObject_IsTrue( pVal ) );

    Py_RETURN_NONE;
}

PyObject * PyPreprocessor_setMicrosoftMode( PyPreprocessor * self, PyObject * args, PyObject * kwds )
{
    static char * kwlist[] = { "value", NULL };

    PyObject * pVal = 0;

    if ( !PyArg_ParseTupleAndKeywords( args, kwds, "O:bool", kwlist, &pVal ) )
    {
        PyErr_SetString( PyExc_Exception, "Failed to parse parameters." );
        return NULL;
    }

    self->pp->setMicrosoftMode( PyObject_IsTrue( pVal ) );

    Py_RETURN_NONE;
}

PyObject * PyPreprocessor_setCPlusPlus( PyPreprocessor * self, PyObject * args, PyObject * kwds )
{
    static char * kwlist[] = { "value", NULL };

    PyObject * pVal = 0;

    if ( !PyArg_ParseTupleAndKeywords( args, kwds, "O:bool", kwlist, &pVal ) )
    {
        PyErr_SetString( PyExc_Exception, "Failed to parse parameters." );
        return NULL;
    }

    self->pp->setCPlusPlus( PyObject_IsTrue( pVal ) );

    Py_RETURN_NONE;
}

PyObject * PyPreprocessor_setMSCVersion( PyPreprocessor * self, PyObject * args, PyObject * kwds )
{
    static char * kwlist[] = { "value", NULL };

    int pVal = 0;

    if ( !PyArg_ParseTupleAndKeywords( args, kwds, "i", kwlist, &pVal ) )
    {
        PyErr_SetString( PyExc_Exception, "Failed to parse parameters." );
        return NULL;
    }

    self->pp->setMSCVersion( pVal );

    Py_RETURN_NONE;
}

PyObject * PyPreprocessor_setThreads( PyPreprocessor * self, PyObject * args, PyObject * kwds )
{
    static char * kwlist[] = { "value", NULL };

    PyObject * pVal = 0;

    if ( !PyArg_ParseTupleAndKeywords( args, kwds, "O:bool", kwlist, &pVal ) )
    {
        PyErr_SetString( PyExc_Exception, "Failed to parse parameters." );
        return NULL;
    }

    self->pp->setThreads( PyObject_IsTrue( pVal ) );

    Py_RETURN_NONE;
}


PyMethodDef PyPreprocessor_methods[] =
{
    {"scanHeaders"     , (PyCFunction)PyPreprocessor_scanHeaders     , METH_VARARGS | METH_KEYWORDS, "Retrieve a list of include files."},
    {"preprocess"      , (PyCFunction)PyPreprocessor_preprocess      , METH_VARARGS | METH_KEYWORDS, "Preprocess a file into a buffer."},
    {"setCPlusPlus"    , (PyCFunction)PyPreprocessor_setCPlusPlus    , METH_VARARGS | METH_KEYWORDS, "Set C++ mode."},
    {"setExceptions"   , (PyCFunction)PyPreprocessor_setExceptions   , METH_VARARGS | METH_KEYWORDS, "Enable exceptions."},
    {"setMicrosoftExt" , (PyCFunction)PyPreprocessor_setMicrosoftExt , METH_VARARGS | METH_KEYWORDS, "Set MS extension mode."},
    {"setMicrosoftMode", (PyCFunction)PyPreprocessor_setMicrosoftMode, METH_VARARGS | METH_KEYWORDS, "Set MS mode."},
    {"setMSCVersion"   , (PyCFunction)PyPreprocessor_setMSCVersion   , METH_VARARGS | METH_KEYWORDS, "Set MSC version."},
    {"setThreads"      , (PyCFunction)PyPreprocessor_setThreads      , METH_VARARGS | METH_KEYWORDS, "Set threads mode."},
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


static PyModuleDef preprocessingModule = {
    PyModuleDef_HEAD_INIT,
    "preprocessor",
    "Module for scanning and collecting header files from C source.",
    -1,
    NULL, NULL, NULL, NULL, NULL
};

PyMODINIT_FUNC PyInit_preprocessing(void)
{
    PyObject * m;

    if ( PyType_Ready( &PyPreprocessingContextType ) < 0 )
        return NULL;
    if ( PyType_Ready( &PyPreprocessorType ) < 0 )
        return NULL;
    m = PyModule_Create( &preprocessingModule );
    if ( m == NULL )
        return NULL;

    Py_INCREF( &PyPreprocessingContextType );
    PyModule_AddObject( m, "PreprocessingContext", (PyObject *)&PyPreprocessingContextType );
    Py_INCREF( &PyPreprocessorType );
    PyModule_AddObject( m, "Preprocessor", (PyObject *)&PyPreprocessorType );
    return m;
}
