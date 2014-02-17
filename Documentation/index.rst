########
BuildPal
########

.. sidebar:: Summary

    :Release: |release|
    :Date: |today|
    :Authors: **Juraj Ivancic**
    :Target: developers
    :status: alpha

Contents:

.. contents::

Motivation
==========

*BuildPal* is a tool for speeding up large C/C++ project builds. Inspired by
the `distcc <https://code.google.com/p/distcc/>`_ project, it works by
distributing parts of build process to other machines on the network.
However, unlike *distcc*, BuildPal's primary target platform is
Windows/Visual C++.

Supported platforms and compilers
=================================

Currently the *only* supported platform is **Windows/Microsoft Visual C++**.
Support for other platforms is :ref:`planned <future-dev-plans>`


Features
========

* **Easy setup**
    No additional files, other than BuildPal Server, are needed on the
    slave machines. All required files will be automatically transferred
    on-demand.

* **Node auto-detection**
    Build nodes on LAN are automatically detected and used.

* **Build consistency**
    BuildPal takes special care to produce object files which are equivalent
    (for all intents and purposes) to the files which would be produced on
    local compilation.

* **Remote preprocessing**
    BuildPal does not preprocess headers on the local machine.
    Instead, all headers required by a source file are collected and
    transfered to the slave [#f1]_ .

* **PCH support**
    BuildPal supports precompiled headers. Precompiled headers are
    created locally, on the client machine and are transferred on-demand
    to specific slave nodes.

Requirements
============

BuildPal Server and Manager are written and tested with Python 3.3. It *will not* work with Python 2.x. It *might* work with Python 3.0 - 3.2

Quick-start
===========

Setting up the Server (slave) node
----------------------------------

* Install BuildPal Server.
* Run distribute_server.py (distribute_server.exe).
    * You can pass the TCP port for server to listen on.
    * You can set the number of jobs.

Run ``distribute_server.py -h`` for more information.

::

    usage: distribute_server.py [-h] [--port #] [--jobs #]

    Command line parameters for distribute_server.py

    optional arguments:
      -h, --help      show this help message and exit
      --port #, -p #  TCP port on which server will listen. (default=6064)
      --jobs #, -j #  Number of jobs, i.e. number of compiler processes that can
                      run concurrently. (default=number of cores)

Setting up the Client
---------------------

* Install BuildPal Manager.
* Create :file:`distribute_manager.ini`.
    * This file must contain configuration for the Manager, namely -- it should
      specify TCP port on which the Manager should listen on, and enumerate
      Server nodes used for compilation.

.. code-block:: ini

    [Manager]
    port=6060

    [Default Profile]
    node[0]=machine0:6064
    node[1]=machine1:6064
    node[2]=machine2:6064

* Run :file:`distribute_manager.py` (:file:`distribute_manager.exe`), optionally
  passing the name of .ini file, and profile to use. The default .ini file is
  :file:`distribute_manager.ini` in the current directory. Default profile name
  is `Default Profile`.

::

    usage: distribute_manager.py [-h] [--ini INI_FILE] [profile]

    Command line parameters for distribute_manager.py

    positional arguments:
      profile         Profile to use. Must be present in the .ini file.

    optional arguments:
      -h, --help      show this help message and exit
      --ini INI_FILE  Specify .ini file.


* Call the compiler
    * Set the environment variable DB_MGR_PORT to the port on which the manager is running on.
    * Replace the :file:`cl.exe` call with :file:`db_cl.exe`.
    * Note that calling MSVC compiler setup scripts (such as ``vcvarsall.bat``) is still required. :file:`db_cl.exe`
      will use its current environment to determine which compiler should be used.

Client
======

The Client (:file:`db_cl.exe`) works as a drop-in replacement for the real
compiler (:file:`cl.exe`). It is designed to be very thin - it contains
almost no compiler-specific knowledge. It sends the command line and any other
relevant environment information to the Manager. After that, it acts as a
puppet -- it enters an event loop in which it processes commands sent by the
Manager. These commands can be:

* ``EXECUTE_AND_EXIT(cmdline)``
    Client creates a process from the given `cmdline` command line and
    exits with the return code from that process. Used e.g. when the Manager
    determines that the call should be completed locally, without
    distributing it to slave nodes.
* ``EXECUTE_GET_OUTPUT(cmdline)``
    Client creates a process from the given `cmdline` command line, 
    captures return code, stdout, stderr and sends them back to the
    manager. This is used by Manager to determine compiler version.
* ``EXIT(retcode, stdout, stderr)``
    Client prints `stdout` to standard output, `stderr` to standard
    error and exits with `retcode` return code.
* ``LOCATE_FILES(file1, file2, ...)``
    For each argument `fileN`, Client locates the file (using first its
    current directory, and then PATH environment variable). Client returns
    the list of absolute path names to the manager. Used to locate compiler
    files when manager needs to send them to one of the slaves.

.. note::

    In order for Client to work, the Manager must already be listening on
    the same machine, and DB_MGR_PORT must be set to its TCP port. Otherwise the
    Client will fail with appropriate error message.

.. todo:: Change client commands to be more secure

    ``EXECUTE_GET_OUTPUT`` and ``EXECUTE_AND_EXIT`` commands can currently run
    any process. This is not needed, as they always run the compiler
    executable. Change it so that only command line arguments are sent, and the
    executable is implied.


Server
======

Server is the part of BuildPal which runs on slave machines.
Capable of storing files which are shared between build processes.

**Workflow**

#. Start listening on TCP port as specified on the command line.
#. Receive a task, which at this point includes a list of all headers required for compiling the task.
#. Check which of these headers are missing/are out of date and send back this list.
#. Receive a bundle which contains all the missing header files, and the source file itself.
    * Header files are cached, so that they are never requested again during the lifetime of the Server process.
#. In case task requires a PCH we do not have - request PCH and cache it.
#. In case we don't have compiler - request compiler and cache it.
    * Cached compiler will, unlike headers and PCH files, be reused if server is restarted.
#. Run the command line as given by the manager, replacing the executable with the compiler we were sent.
#. Send the retcode, stdout, and stderr to the manager.
#. If retcode == 0 send the resulting object file.
#. In case there was an exception before the compiler was run, notify manager.

Manager
=======

The manager is the most complex part of the BuildPal suite.
Contains all compiler-specific knowledge.
Runs locally, on the client machine.

**Workflow**

#. Start listening on predetemined port.
#. Receive connection from Client.
#. Receive command line from Client connection.
#. Process command line and create tasks.
#. Each source file to be compiled is wrapped in a separate task.
#. Manager can decide to allow the client to run the command locally.
    * This is done when creating PCH file.
#. For each task, Manager 'preprocesses' its source file to determine headers needed for its compilation.
#. Once preprocessing is done, Manager selects a slave node it considers to be the best candidate for compiling the task.
#. Manager uses 2-way handshake with the slave to determine which of the required headers are missing on the slave.
#. Manager sends the missing headers.
#. Manager sends PCH file, if required, to the slave.
#. Manager waits for task completion.
#. In case Server failed to run the task successfully, manager will retry the task.
    * Note that failed task here means that slave did not reach phase of running the compiler.
    * Once the compiler is executed, the task is considered successful, even if the compilation fails.
#. Send the result to the Client.
    

3-rd party
==========

* `Python <http://www.python.org>`_

* `ZeroMQ <http://www.zeromq.org>`_

    Used to implement all IPC.
    Current windows implementation has limitations. There is no pipe/shm
    support, which would be ideal for Client-Manager IPC, as they
    always reside on the same machine. Currently loopback TCP interface
    is used instead.

* `LLVM <http://www.llvm.org>`_

    A bunch of utility classes which fit in nicely in this project.

* `Clang <http://clang.llvm.org>`_

    ClangLex is used by Manager to get a list of headers required by a source file.
    Clang argument parser is used by Manager to parse command line.

* `Boost <http://www.boost.org>`_

    Used by all C++ parts of the project.
        * *Boost.ASIO* for Client's (:file:`db_cl.exe`) TCP communication.
        * *Boost.MultiIndex* for Managers header cache.
        * *Boost.Spirit* as an alternative to ``atoi``/``itoa``/etc.
        * *Boost.Thread* for read-write mutexes.
        * ...

Benchmarks
==========

Currently BuildPal is mainly tested by building `Boost`_ libraries. Boost
libraries make heavy use of preprocessor, and are thus ideal candidates for
testing both speed and sanity.

Building Boost was done with the following command, after modifying
Boost.Build to use BuildPal's compiler instead of the native msvc
compiler executable::

    bjam stage --stagedir=. -a -j ##

The host machine was not a farm node in distributed compilation.
Tested Boost library version: 1.53.

Environment.
    * 100Mbit/s Ethernet network.
    * Client machine: HP Pavillion g7 notebook with Intel i3 processor (4 cores).
    * Slave #1. Dell notebook with i7 processor (8 cores).
    * Slave #2. Speedtest (8 cores).
    * Slave #3. Asus notebook, 4 cores.

+---------------+------------+-----------+-----------+-----------+
|               |            |           |           |           |
| type          | parallel # |  local    |  2 nodes  |  3 nodes  |
|               |            |           |           |           |
+===============+============+===========+===========+===========+
| regular build | 4  tasks   |  8:01.02  |           |           |
+---------------+------------+-----------+-----------+-----------+
| distributed   | 4  tasks   |           |  5:11.88  |  5:29.39  |
+---------------+------------+-----------+-----------+-----------+
| distributed   | 16 tasks   |           |  2:30.74  |  2:20.66  |
+---------------+------------+-----------+-----------+-----------+
| distributed   | 32 tasks   |           |  2:07.34  |  2:06.61  |
+---------------+------------+-----------+-----------+-----------+
| distributed   | 40 tasks   |           |  2:06.59  |  2:00.73  |
+---------------+------------+-----------+-----------+-----------+

Note that these values are just informative. There is a circa 10 second standard
deviation due to the fact that benchmarking was done in an office network.


Bugs and caveats
================

* Header cache and volatile search path
    Cache assumes that a concrete search path and header name will always
    resolve to the same file. In case a new header file is generated and put in
    a directory on include path before the old header file, this will not be
    seen by the cache, and old header will be used instead.

* Visual Studio 2008
    Using BuildPal with Visual Studio 2008 can trigger a compiler bug with
    precompiled headers. To fix the issue see `KB976656 <http://archive.msdn.microsoft.com/KB976656>`_.

.. _future-dev-plans:

Future development plans
========================

* Support more platforms.
    * Support GCC on Windows (MinGW).
    * Support GCC on Linux.
    * Support Clang.
    * ...

* Implement broken (invalid) connection detection using heart-beats.
    * see `ZeroMQ Guide <http://zguide.zeromq.org/page:all#Chapter-Reliable-Request-Reply-Patterns>`_.


.. rubric:: Footnotes

.. [#f1] Granted, for this to be done correctly, some source file
        preprocessing is required. This part has been optimized
        and is orders of magnitude faster than 'real' preprocessing.

