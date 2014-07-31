Quick Start
###########

Requirements
============

1. A C/C++ project, using a build system capable of running parallel
   tasks.

2. A client build machine connected to a Local-Area Network.

3. As many as possible machines (slaves) on LAN capable of running the compiler
   your C/C++ project uses.

    * Given that the only compiler currently supported is MSVC, this means that
      all slave machines need to run Windows.

Get the installer
=================

* Get the `BuildPal installer <https://sourceforge.net/projects/buildpal/>`_ from SourceForge.

Setting up Server (slave) machines
==================================

On each machine:

* Install ``BuildPal``.
* Run the `BuildPal Server` shortcut from the newly created program group.

That's it - the server will be automatically discovered by client machine via
UDP multicast.

.. note:

    Slaves do not need to have compiler pre-installed. However, C++
    redistributable package the compiler uses should be installed.


Setting up the Client
=====================

* Install ``BuildPal`` on the Client machine.
* Run the `BuildPal Manager` shortcut from the newly created program group.
    * The Manager is the mediator between a compilation request and the build farm. It performs many tasks, including:
        * Server detection.
        * All network communication towards the farm.
        * All (IPC) communication with the clients (i.e. compilation requests).
        * Source file preprocessing.
            * Needed in order to determine which files are required for successful remote compilation.
        * Local filesystem information caching.
            * Source file contents.
            * Preprocessing results.
* Run the 'Buildpal Console' shortcut.
    * This opens a new command line window. From here you should start your
      build. Any compiler processes started from this console will be
      intercepted and distributed to farm.
    * When starting your build, increase the number of parallel jobs (typically
      ``-jN`` option).

BuildPal Console
================

The console is used to run the build. It is a regular ``cmd.exe`` console, with
installed hooks which detect when a compiler process is created.

BuildPal has two types of consoles, each using a different method
of intercepting compilation requests.

.. _compiler_substitution:

Compiler Substitution (default)
-------------------------------

``BuildPal`` provides a drop-in compiler subtitute :program:`bp_cl`. When
``BuildPal`` detects that the compiler process is about to be created, it replaces the
call to :program:`cl` to :program:`bp_cl`. Note that :program:`bp_cl` is
small and relatively lightweight, so most modern hardware should not have any
problems in running many concurrently.

.. _createprocess_hooking:

CreateProcess Hooking (experimental)
------------------------------------

There is a faster, albeit less general and less safe method.

The idea is to intercept all calls a build system makes to the compiler, and to
delegate this work to the farm, completely avoiding compiler process creation on
the client machine. ``BuildPal`` will try to fool the build system into thinking
that a process was actually created.

This approach works for most build systems. It will not work if the build system
attempts do to anything 'smart' with the (supposedly) created compiler process.
For example, this technique does not work with ``MSBuild``.

.. note:

    With this method you can go wild with the ``-j`` option - use as much as
    your build will allow. As there is no process creation there will be very
    little overhead.

Using BuildPal as a Python package
==================================

If you have built BuildPal yourself, you can use it from Python without actually
creating the installer.

Starting the server::

    python -m buildpal server

Starting the manager::

    python -m buildpal manager

Starting the build (compiler substitution)::

    python -m buildpal client --run <build_command>

Starting the build (CreateProcess hooking)::

    python -m buildpal client --no-cp --run <build_command>

