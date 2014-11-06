* Speed optimizations.
    * Currently building Chromium with BuildPal does not speed up
      its build process by very much.

* Avoid sending include path to the server with every task.
    * Instead, make sure that header list being sent is in the correct order.

* Include order test does not work.

* Clean up manager timers.
    * Current names are cryptic.
    * Should not be given so much GUI exposure.

* Server task counter.
    * Server task counter is sometimes out of sync.

