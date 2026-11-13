# -*- coding: utf-8 -*-
"""Cold IronPython CSV validation on a 1 MiB stack, without opening Revit.

Run first through run_ironpython.ps1. The former nested exception handlers
overflowed this stack when point IDs were selected as floor layers. A normal
unittest run on a larger stack, or after JIT warmup, did not expose the crash.
"""
from __future__ import unicode_literals
import codecs
import os
import sys
import tempfile
from System.Threading import Thread, ThreadStart

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import topobim_floor_csv as csv_floors
import topobim_floor_geometry as geom

failures = []


def check_invalid(path, expected):
    try:
        csv_floors.read_areas(path)
    except ValueError as error:
        assert expected in unicode(error), unicode(error)
        return
    raise AssertionError('Invalid input was accepted')


def check_stack():
    handle, path = tempfile.mkstemp(suffix='.csv')
    os.close(handle)
    try:
        # Each point ID becomes a separate one-vertex, invalid contour.
        with codecs.open(path, 'w', 'utf-8') as stream:
            stream.write('E;N;Z;Layer\n')
            for i in range(500):
                stream.write('{0};{0};0;P{0}\n'.format(i))
        check_invalid(path, 'Confira a coluna de layer')

        # Invalid layers must not prevent a later, valid layer being reviewed.
        with codecs.open(path, 'a', 'utf-8') as stream:
            stream.write('0;0;0;VALIDO\n2;0;0;VALIDO\n0;2;0;VALIDO\n')
        areas, issues = csv_floors.read_areas(path)
        assert list(areas) == ['VALIDO']
        assert geom.region_area(areas['VALIDO'][0]) == 2
        assert len(issues) == 500

        # Malformed rows are also handled without accumulating stack frames.
        with codecs.open(path, 'w', 'utf-8') as stream:
            stream.write('E;N;Z;Layer\n' + 'bad;0;0;A\n' * 500)
        check_invalid(path, 'Linha 2:')
    except Exception as error:
        failures.append(unicode(error))
    finally:
        os.remove(path)


worker = Thread(ThreadStart(check_stack), 1024 * 1024)
worker.Start()
worker.Join()
assert not failures, '\n'.join(failures)
print('IronPython CSV: 500 invalid layers/rows on a cold 1 MiB stack: OK')
