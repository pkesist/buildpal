Quick Start
===========

Requirements
------------

1. A C/C++ project (duh) using a build system capable of running parallel
   tasks.

2. A client build machine connected to a Local-Area Network.

3. As many as possible machines (slaves) on LAN capable of running the compiler
   your C/C++ project uses.

    * Given that the only compiler currently supported is MSVC, this means that
      all slave machines need to run Windows.

Setting up the Server (slave) nodes
-----------------------------------

On each slave on the network do the following:

* Grab the installer from SourceForge.
* Install it. This will create 'BuildPal Server' shortcut on your desktop.
* Run the shortcut.

.. note:

    There is no need to explicitly specify TCP port. Each server is
    automatically discovered (via UDP multicast).

.. note:

    Slaves do not need to have compiler pre-installed.

Setting up the Client
---------------------

* Grab the installer from SourceForge.
* Install it. This will create 'BuildPal Manager' shortcut on your desktop.
* In addition, there will be a :file:`bp_cl.exe` file in the installation
  directory.

* Run Manager.
    * This will open Manager's GUI which can be used to view detected farm
      configuration. If this is satisfactory, run the Manager by pressing its
      `Start` button.

* Configure the build system.
    * You must configure your build system to use :file:`bp_cl.exe` instead of
      MSVC :file:`cl.exe`.
    * For information on how to integrate with some build systems see :ref:`here \
      <integrating-with-build-systems>`.

.. note::

    Calling MSVC compiler setup scripts (such as ``vcvarsall.bat``) is still
    required. :file:`bp_cl.exe` uses the environment to locate the compiler,
    system headers etc.

* Run the build.
    * Number of concurrent jobs should be set to as many as your machine can
      manage.
