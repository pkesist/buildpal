#include "client.hpp"

#include <Python.h>

struct CallPyObjInfo
{
    PyObject * callable;
    PyObject * args;
    PyObject * kwArgs;
    PyThreadState * * threadState;
};

int callPyObj( char const * reason, void * vpCallPyObj )
{
    CallPyObjInfo * const callPyObjInfo( reinterpret_cast<CallPyObjInfo *>( vpCallPyObj ) );
    PyEval_RestoreThread( *callPyObjInfo->threadState );
    PyObject * kwArgs;
    if ( callPyObjInfo->kwArgs )
    {
        kwArgs = callPyObjInfo->kwArgs;
        Py_INCREF( kwArgs );
    }
    else
    {
        kwArgs = PyDict_New();
    }
    PyDict_SetItemString( kwArgs, "reason", PyUnicode_FromString( reason ) );
    PyObject * resultObj = PyObject_Call( callPyObjInfo->callable, callPyObjInfo->args, kwArgs );
    Py_DECREF( kwArgs );
    int result;
    if ( !resultObj || !PyLong_Check( resultObj ) )
        result = -2;
    else
        result = static_cast<int>( PyLong_AsLong( resultObj ) );
    *callPyObjInfo->threadState = PyEval_SaveThread();
    return result;

}

PyDoc_STRVAR(Client_distributedCompileDoc,
"compile(toolset, executable, environment, cmd_line, cwd, port_name, \n\
         fallback_func, fallback_args, fallback_kwargs) -> int\n\
\n");

PyObject * Client_distributedCompile( PyObject * self, PyObject * args, PyObject * kwArgs )
{
    char * keywords[] =
    {
        "toolset",
        "executable",
        "environment",
        "command_line",
        "port_name",
        "cwd",
        "fallback_func",
        "fallback_args",
        "fallback_kwargs"
    };

    char const * compilerToolset = 0;
    char const * compilerExecutable = 0;
    PyObject * environment = 0;
    char const * commandLine = 0;
    char const * portName = 0;
    char const * cwd = 0;
    PyObject * fallbackFunc = 0;
    PyObject * fallbackArgs = 0;
    PyObject * fallbackKwArgs = 0;

    if
    (
        !PyArg_ParseTupleAndKeywords
        (
            args, kwArgs, "ssOss|sOOO:compile", keywords,
            &compilerToolset,
            &compilerExecutable,
            &environment,
            &commandLine,
            &portName,
            &cwd,
            &fallbackFunc,
            &fallbackArgs,
            &fallbackKwArgs
        )
    )
        return NULL;

    Environment env;
    PyObject * key;
    PyObject * value;
    Py_ssize_t pos( 0 );
    if ( !PyDict_Check( environment ) )
        return NULL;

    while ( PyDict_Next( environment, &pos, &key, &value ) )
    {
        PyObject * const keyAscii( PyUnicode_AsASCIIString( key ) );
        PyObject * const valueAscii( PyUnicode_AsASCIIString( value ) );
        if ( keyAscii && valueAscii )
        {
            env.add( PyBytes_AsString( keyAscii ), PyBytes_AsString( valueAscii ) );
            Py_DECREF( keyAscii );
            Py_DECREF( valueAscii );
        }
        else
        {
            Py_XDECREF( keyAscii );
            Py_XDECREF( valueAscii );
            return NULL;
        }
    };

    if ( fallbackFunc )
    {
        if ( !PyCallable_Check( fallbackFunc ) )
            return NULL;
        if ( !fallbackArgs )
            fallbackArgs = PyTuple_New( 0 );
        else
            Py_INCREF( fallbackArgs );
    }

    int result;
    {
        struct AllowThreads
        {
            PyThreadState * save_;
            AllowThreads() { save_ = PyEval_SaveThread(); }
            ~AllowThreads() { PyEval_RestoreThread( save_ ); }
        } gilGuard;

        CallPyObjInfo callPyObjInfo = {
            fallbackFunc,
            fallbackArgs,
            fallbackKwArgs,
            &gilGuard.save_
        };
        FallbackFunction fallbackFunction( 0 );
        void * fallbackArguments( 0 );
        if ( fallbackFunc )
        {
            fallbackFunction = callPyObj;
            fallbackArguments = &callPyObjInfo;
        }

        result = distributedCompile( compilerToolset, compilerExecutable, env,
            commandLine, cwd, portName, fallbackFunction, fallbackArguments );
    }

    if ( fallbackFunc )
        Py_DECREF( fallbackArgs );

    return PyLong_FromLong( result );
}

static PyMethodDef clientMethods[] = {
    {"compile", (PyCFunction)Client_distributedCompile, METH_VARARGS | METH_KEYWORDS, Client_distributedCompileDoc},
    {NULL, NULL, 0, NULL}
};

static PyModuleDef clientModule = {
    PyModuleDef_HEAD_INIT,
    "buildpal_client",
    "Module containing BuildPal Client functionality.",
    -1,
    clientMethods, NULL, NULL, NULL, NULL
};

PyMODINIT_FUNC PyInit_buildpal_client(void)
{
    return PyModule_Create( &clientModule );
}
