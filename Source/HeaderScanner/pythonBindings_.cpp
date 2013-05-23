#include "headerScanner_.hpp"

#include <Python.h>

typedef struct {
    PyObject_HEAD
    PreprocessingContext * ppContext;
} HeaderScanner;

void HeaderScanner_dealloc( HeaderScanner * self )
{
    delete self->ppContext;
    Py_TYPE(self)->tp_free( (PyObject *)self );
}

PyObject * HeaderScanner_new( PyTypeObject * type, PyObject * args, PyObject * kwds )
{
    HeaderScanner * self;
    self = (HeaderScanner *)type->tp_alloc( type, 0 );
    return (PyObject *)self;
}

int HeaderScanner_init( HeaderScanner  *self, PyObject * args, PyObject * kwds )
{
    static char * kwlist[] = { "filename", NULL };

    char const * filename = 0;

    if ( !PyArg_ParseTupleAndKeywords( args, kwds, "s", kwlist, &filename ) )
        return -1;

    delete self->ppContext;
    self->ppContext = new PreprocessingContext( filename );
    return 0;
}

PyObject * HeaderScanner_add_include_path( HeaderScanner * self, PyObject * args, PyObject * kwds )
{
    static char * kwlist[] = { "path", "sysinclude", NULL };

    char const * path = 0;
    PyObject * sysInclude = Py_False;

    if ( !PyArg_ParseTupleAndKeywords( args, kwds, "s|O:bool", kwlist, &path, &sysInclude ) )
        return NULL;

    if ( !self->ppContext )
        return NULL;

    self->ppContext->addIncludePath( path, PyObject_IsTrue( sysInclude ) );
    Py_RETURN_NONE;
}

PyObject * HeaderScanner_scan_headers( HeaderScanner * self )
{
    if ( !self->ppContext )
        return NULL;

    PreprocessingContext::HeaderRefs const headers = self->ppContext->scanHeaders();
    
    PyObject * result = PyTuple_New( headers.size() );
    unsigned int index( 0 );
    for ( PreprocessingContext::HeaderRefs::const_iterator iter = headers.begin(); iter != headers.end(); ++iter )
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

PyMethodDef HeaderScanner_methods[] =
{
    {"add_include_path", (PyCFunction)HeaderScanner_add_include_path, METH_VARARGS, "Add a search path."               },
    {"scan_headers"    , (PyCFunction)HeaderScanner_scan_headers    , METH_NOARGS , "Retrieve a list of include files."},
    {NULL}
};

PyTypeObject HeaderScannerType = {
    PyVarObject_HEAD_INIT(NULL, 0)
    "HeaderScanner",                   /* tp_name */
    sizeof(HeaderScanner),             /* tp_basicsize */
    0,                                 /* tp_itemsize */
    (destructor)HeaderScanner_dealloc, /* tp_dealloc */
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
    "HeaderScanner object",            /* tp_doc */
    0,                                 /* tp_traverse */
    0,                                 /* tp_clear */
    0,                                 /* tp_richcompare */
    0,                                 /* tp_weaklistoffset */
    0,                                 /* tp_iter */
    0,                                 /* tp_iternext */
    HeaderScanner_methods,             /* tp_methods */
    0,                                 /* tp_members */
    0,                                 /* tp_getset */
    0,                                 /* tp_base */
    0,                                 /* tp_dict */
    0,                                 /* tp_descr_get */
    0,                                 /* tp_descr_set */
    0,                                 /* tp_dictoffset */
    (initproc)HeaderScanner_init,      /* tp_init */
    0,                                 /* tp_alloc */
    HeaderScanner_new,                 /* tp_new */
};

static PyModuleDef headerScannerModule = {
    PyModuleDef_HEAD_INIT,
    "headerscanner",
    "Module for scanning and collecting header files from C source.",
    -1,
    NULL, NULL, NULL, NULL, NULL
};

PyMODINIT_FUNC PyInit_header_scanner(void)
{
    PyObject * m;

    if ( PyType_Ready( &HeaderScannerType ) < 0 )
        return NULL;
    m = PyModule_Create( &headerScannerModule );
    if ( m == NULL )
        return NULL;

    Py_INCREF( &HeaderScannerType );
    PyModule_AddObject( m, "HeaderScanner", (PyObject *)&HeaderScannerType );
    return m;
}
