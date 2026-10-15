Grouped
=======

Servers, missing only
---------------------

.. duvet-report:: spec/rfc9999.txt
   :targets: role=server
   :group-by: role
   :show: missing

Servers, unannotated only
-------------------------

.. duvet-report:: spec/rfc9999.txt
   :targets: role=server
   :group-by: role
   :show: unannotated

Section 2.1, MAY
----------------

.. duvet-report:: spec/rfc9999.txt
   :sections: 2.1
   :levels: may

Nothing
-------

.. duvet-report:: spec/rfc9999.txt
   :sections: 1
