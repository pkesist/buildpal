Quick-start
===========

If the :ref:`requirements <requirements>` are met, you can proceed to setting up the farm.

Setting up the Server (slave) nodes
-----------------------------------

On each slave on the network do the following:

* Grab the installer from SourceForge.
* Install it. This will create 'BuildPal Server' shortcut on your desktop.
* Run the shortcut.

.. note:

    There is no need to explicitly specify TCP port. Each server is
    automatically discovered using UDP multicast.

.. note:

    Slaves do not need to have compiler pre-installed.

Setting up the Client
---------------------

* Grab the installer from SourceForge.
* Install it. This will create 'BuildPal Manager' shortcut on your desktop.
* In addition, there will be a :file:`bp_cl.exe` file in the installation
  directory.
* Configure the build system.
    * As mentioned, to utilize the build farm, a build system capable of
      concurrently running build tasks is required. More about this can be found
      :ref:`integrating-with-build-systems`
    * You must configure your build system to use :file:`bp_cl.exe` instead of
      MSVC-s :file:`cl.exe`.

.. note::

    Note that for executing :file:`bp_cl.exe`, calling MSVC compiler setup
    scripts (such as ``vcvarsall.bat``) is still required. :file:`bp_cl.exe`
    uses its environment to locate the real compiler :file:`cl.exe`.

3. Run BuildPal Manager.
    * This will open Manager's GUI which can be used to view detected farm
      configuration. If this is satisfactory, run the Manager by pressing its
      `Start` button.

4. Run the build.
    * Number of concurrent jobs should be set to as many as your machine can
      manage.
