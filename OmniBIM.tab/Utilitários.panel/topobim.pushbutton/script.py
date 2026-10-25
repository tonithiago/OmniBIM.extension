# -*- coding: utf-8 -*-
"""TOPOBIM: levantamentos CSV/TXT e DWG para sólidos topográficos."""
from pyrevit import forms, revit, HOST_APP, script

__cleanengine__ = True
__persistentengine__ = False


def main():
    if str(HOST_APP.version) != '2026':
        forms.alert(u'O TOPOBIM requer Revit 2026.', title='TOPOBIM')
        return
    doc = revit.doc
    if doc is None or doc.IsFamilyDocument:
        forms.alert(u'Abra um projeto Revit para criar o terreno.', title='TOPOBIM')
        return
    if doc.IsReadOnly or doc.IsLinked:
        forms.alert(u'O projeto precisa estar disponível para edição.', title='TOPOBIM')
        return
    from topobim_ui import TopoBimWindow
    window = TopoBimWindow(revit.uidoc, script.get_logger())
    window.ShowDialog()
    if window.requested_review_view_id:
        from topobim_revit import show_review_view
        try:
            show_review_view(revit.uidoc,window.requested_review_view_id)
        except Exception as error:
            script.get_logger().exception('TOPOBIM: abrir vista após criação')
            forms.alert(u'Os elementos foram criados. Não foi possível abrir a vista 3D: {0}'.format(error),title='TOPOBIM')


if __name__ == '__main__':
    main()
