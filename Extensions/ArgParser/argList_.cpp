#include "clangOpts_.hpp"

#include "llvm/Option/Arg.h"
#include "llvm/Option/ArgList.h"
#include "llvm/Option/OptTable.h"
#include "llvm/Option/Option.h"
#include "llvm/Option/OptSpecifier.h"
#include "llvm/Support/raw_ostream.h"
#include "clang/Driver/Options.h"

#include "Python.h"

static PyModuleDef parseArgsModule = {
    PyModuleDef_HEAD_INIT,
    "parse_args",
    "Module for parsing compiler command line options.",
    -1,
    NULL, NULL, NULL, NULL, NULL
};


////////////////////////////////////////////////////////////////////////////////
//
// ---------
// PyArgList
// ---------
//
////////////////////////////////////////////////////////////////////////////////

typedef struct {
    PyObject_HEAD
    llvm::opt::InputArgList * argList;
} PyArgList;

void PyArgList_dealloc( PyArgList * self )
{
    delete self->argList;
    Py_TYPE(self)->tp_free( (PyObject *)self );
}

PyObject * PyArgList_new( PyTypeObject * type, PyObject * args, PyObject * kwds )
{
    PyArgList * self;
    self = (PyArgList *)type->tp_alloc( type, 0 );
    return (PyObject *)self;
}

int PyArgList_init( PyArgList * self, PyObject * args, PyObject * kwds )
{
    static char * kwlist[] = { "args", NULL };
    PyObject * argList = 0;

    if ( !PyArg_ParseTupleAndKeywords( args, kwds, "O", kwlist, &argList ) )
    {
        PyErr_SetString( PyExc_Exception, "Invalid args parameter." );
        return -1;
    }

    if ( !argList || !PyList_Check( argList ) )
    {
        PyErr_SetString( PyExc_Exception, "Parameter must be a list of arguments." );
        return 0;
    }

    std::size_t const argCount = PyList_Size( argList );
    std::vector<char const *> argListCPtrs( argCount );
    for ( unsigned int index( 0 ); index < argCount; ++index )
    {
        PyObject * listItem = PyList_GetItem( argList, index );
        if ( !PyUnicode_Check( listItem ) )
        {
            PyErr_SetString( PyExc_Exception, "Found non-string argument." );
            return 0;
        }   
        argListCPtrs[ index ] = PyUnicode_AsUTF8( listItem );
    }


    unsigned missingArgIndex, missingArgCount;
    self->argList = unaliasedOptTable().ParseArgs( &argListCPtrs[0], &argListCPtrs[0] + argCount, missingArgIndex, missingArgCount );
    return 0;
}

PyObject * PyArgList_optionNames( PyArgList * self )
{
    PyObject * list = PyList_New( self->argList->getArgs().size() );
    unsigned int index = 0;
    for ( auto argPtr : self->argList->getArgs() )
    {
        llvm::StringRef const optName( argPtr->getOption().getName() );
        PyList_SetItem( list, index, PyUnicode_FromStringAndSize( optName.data(), optName.size() ) );
        ++index;
    }
    return list;
}

PyObject * PyArgList_optionValues( PyArgList * self )
{
    PyObject * list = PyList_New( self->argList->getArgs().size() );
    unsigned int index = 0;
    for ( auto argPtr : self->argList->getArgs() )
    {
        llvm::opt::ArgStringList newArgs;
        argPtr->renderAsInput( *self->argList, newArgs );
        unsigned int const valuesCount = argPtr->getNumValues();
        PyObject * subList = PyList_New( valuesCount );
        for ( unsigned int subIndex = 0; subIndex < valuesCount; ++subIndex )
        {
            PyList_SetItem( subList, subIndex, PyUnicode_FromString( argPtr->getValue( subIndex ) ) );
        }
        PyList_SetItem( list, index, subList );
        ++index;
    }
    return list;
}

PyObject * PyArgList_argValues( PyArgList * self )
{
    PyObject * list = PyList_New( self->argList->getArgs().size() );
    unsigned int index = 0;
    for ( auto argPtr : self->argList->getArgs() )
    {
        llvm::opt::ArgStringList newArgs;
        argPtr->renderAsInput( *self->argList, newArgs );
        PyObject * subList = PyList_New( newArgs.size() );
        unsigned int subIndex = 0;
        for ( llvm::StringRef part : newArgs )
        {
            PyList_SetItem( subList, subIndex, PyUnicode_FromStringAndSize( part.data(), part.size() ) );
            ++subIndex;
        }
        PyList_SetItem( list, index, subList );
        ++index;
    }
    return list;
}


PyMethodDef PyArgList_methods[] =
{
    {"option_names" , (PyCFunction)PyArgList_optionNames, METH_NOARGS, "Get a list of option names."},
    {"option_values", (PyCFunction)PyArgList_optionValues, METH_NOARGS, "Get a list of option values."},
    {"arg_values", (PyCFunction)PyArgList_argValues, METH_NOARGS, "Get a list of command line arguments."},
    {NULL}
};

PyTypeObject PyArgListType = {
    PyVarObject_HEAD_INIT(NULL, 0)
    "ArgList",                     /* tp_name */
    sizeof(PyArgList),             /* tp_basicsize */
    0,                             /* tp_itemsize */
    (destructor)PyArgList_dealloc, /* tp_dealloc */
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
    "ArgList object",              /* tp_doc */
    0,                             /* tp_traverse */
    0,                             /* tp_clear */
    0,                             /* tp_richcompare */
    0,                             /* tp_weaklistoffset */
    0,                             /* tp_iter */
    0,                             /* tp_iternext */
    PyArgList_methods,             /* tp_methods */
    0,                             /* tp_members */
    0,                             /* tp_getset */
    0,                             /* tp_base */
    0,                             /* tp_dict */
    0,                             /* tp_descr_get */
    0,                             /* tp_descr_set */
    0,                             /* tp_dictoffset */
    (initproc)PyArgList_init,      /* tp_init */
    0,                             /* tp_alloc */
    PyArgList_new,                 /* tp_new */
};


PyMODINIT_FUNC PyInit_parse_args(void)
{
    if ( PyType_Ready( &PyArgListType ) < 0 )
        return NULL;

    PyObject * m = PyModule_Create( &parseArgsModule );
    if ( m == NULL )
        return NULL;

    Py_INCREF( &PyArgListType );
    PyModule_AddObject( m, "ArgList", (PyObject *)&PyArgListType );
    return m;
}
