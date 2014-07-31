``BuildPal`` and some build systems
===================================

``BuildPal`` works best with build systems which support ``-j`` option.
Although every build system will work with *compiler substition* hook,
*createprocess* hook will work better. Here is the current state of affairs
some common build systems:

+--------------------------+-------------+--------+
|                          |has -j option|supports|
|  Build system            |             |cp hook |
+==========================+=============+========+
| Boost.Build              | yes         | yes    |
+--------------------------+-------------+--------+
| JOM                      | yes         | yes    |
+--------------------------+-------------+--------+
| MSBuild                  | no          | no     |
+--------------------------+-------------+--------+
| Ninja                    | yes         | yes    |
+--------------------------+-------------+--------+
| Nmake                    | no          | yes    |
+--------------------------+-------------+--------+
| SCons                    | yes         | yes    |
+--------------------------+-------------+--------+

It seems that Microsoft really goes out of its way to prevent parallel build
support with their build systems.