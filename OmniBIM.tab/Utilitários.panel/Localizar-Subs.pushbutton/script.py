# -*- coding: utf-8 -*-
__title__ = "Localizar/Substituir"
__docs__ = "Localiza e substitui parâmetros de texto, notas, vistas e folhas com pré-visualização em tabela."

from Autodesk.Revit.DB import *
from pyrevit import revit, forms
from System.Collections.Generic import List
import clr
import re

clr.AddReference("System")
doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument


def obter_nome_elemento(el):
    try:
        if isinstance(el, TextNote):
            return u"Nota de Texto"
        if isinstance(el, ViewSheet):
            return u"Folha: {}".format(el.SheetNumber)
        if isinstance(el, View):
            return u"Vista: {}".format(el.Name)
        cat = el.Category.Name if el.Category else u"Elemento"
        nome = getattr(el, "Name", None)
        return u"{}{}".format(cat, u" - {}".format(nome) if nome else u"")
    except:
        return u"Elemento"


def limpar_texto_exibicao(texto):
    if texto is None:
        return u""
    try:
        texto = unicode(texto)
    except NameError:
        texto = str(texto)
    return u" ".join([linha.strip() for linha in texto.splitlines() if linha.strip()])


class ParametroItem(object):
    """Linha da tabela de pré-visualização; mantém a referência ao elemento/parâmetro Revit."""
    def __init__(self, element, param=None, is_text_note=False, is_view_name=False):
        self.element = element
        self.param = param
        self.is_text_note = is_text_note
        self.is_view_name = is_view_name
        self.IsSelected = True
        self.ItemId = str(element.Id.IntegerValue if hasattr(element.Id, "IntegerValue") else element.Id.Value)
        self.ElementItem = obter_nome_elemento(element)
        self.FieldName = u""
        self.CurrentText = u""
        self.ProposedText = u""
        self.Status = u"Válido"
        self.Details = u"Pronto para aplicar."

        if param:
            self.FieldName = param.Definition.Name
            self.CurrentText = param.AsString() or u""
        elif is_text_note:
            self.FieldName = u"Texto da Nota"
            self.CurrentText = element.Text or u""
        elif is_view_name:
            self.FieldName = u"Nome da Vista/Folha"
            self.CurrentText = element.Name or u""

        self.ProposedText = self.CurrentText


class JanelaLocalizarSubstituir(forms.WPFWindow):
    def __init__(self, xaml_file_name):
        forms.WPFWindow.__init__(self, xaml_file_name)
        self.elementos_escopo = []
        self.itens_encontrados = []

        self.cbViewTypes.SelectionChanged += self.ao_mudar_escopo
        self.tbFind.TextChanged += self.atualizar_busca
        self.tbReplace.TextChanged += self.atualizar_preview
        self.btnSelectAll.Click += self.selecionar_tudo
        self.btnSelectNone.Click += self.limpar_selecao
        self.btnLocate.Click += self.localizar_no_revit
        self.btnCancel.Click += self.fechar_janela
        self.btnRename.Click += self.executar_substituicao
        self.carregar_escopo()

    def AoDuploCliqueItem(self, sender, args):
        self.localizar_no_revit(None, None)

    def localizar_no_revit(self, sender, args):
        item = self.dgResults.SelectedItem
        if not item:
            forms.alert(u"Selecione uma linha da tabela para localizar no Revit.")
            return
        try:
            el = item.element
            if not el or not el.IsValidObject:
                forms.alert(u"O elemento não é mais válido no documento.")
                return
            ids = List[ElementId]()
            ids.Add(el.Id)
            uidoc.Selection.SetElementIds(ids)
            if isinstance(el, View) and not el.IsTemplate:
                uidoc.ActiveView = el
            else:
                uidoc.ShowElements(el.Id)
        except Exception as e:
            forms.alert(u"Não foi possível focar o elemento: {}".format(e))

    def ao_mudar_escopo(self, sender, args):
        self.carregar_escopo()
        self.atualizar_busca(None, None)

    def carregar_escopo(self):
        idx = self.cbViewTypes.SelectedIndex
        self.elementos_escopo = []
        if idx == 1:
            for eid in uidoc.Selection.GetElementIds():
                el = doc.GetElement(eid)
                if el:
                    self.elementos_escopo.append(el)
            return
        if idx in [3, 5]:
            self.elementos_escopo.extend(FilteredElementCollector(doc).OfClass(TextNote).WhereElementIsNotElementType().ToElements())
        if idx in [2, 4, 5]:
            vistas = [v for v in FilteredElementCollector(doc).OfClass(View).WhereElementIsNotElementType().ToElements() if not v.IsTemplate and not isinstance(v, ViewSchedule)]
            folhas = list(FilteredElementCollector(doc).OfClass(ViewSheet).WhereElementIsNotElementType().ToElements())
            tabelas = [t for t in FilteredElementCollector(doc).OfClass(ViewSchedule).WhereElementIsNotElementType().ToElements() if not t.IsTemplate]
            self.elementos_escopo.extend(vistas)
            self.elementos_escopo.extend(folhas)
            self.elementos_escopo.extend(tabelas)
        if idx in [0, 5]:
            todos = FilteredElementCollector(doc).WhereElementIsNotElementType().ToElements()
            for el in todos:
                try:
                    if el.Category and el.Category.CategoryType == CategoryType.Model:
                        if idx == 0:
                            try:
                                cid = el.Category.Id
                                if cid == ElementId(BuiltInCategory.OST_PropertySet) or cid == ElementId(BuiltInCategory.OST_MaterialAssets):
                                    continue
                            except:
                                pass
                        self.elementos_escopo.append(el)
                except:
                    continue

    def atualizar_busca(self, sender, args):
        find_str = self.tbFind.Text or u""
        self.itens_encontrados = []
        if not find_str:
            self.dgResults.ItemsSource = self.itens_encontrados
            self.lblSelectedCount.Text = u"Digite o texto para localizar"
            self.atualizar_preview(None, None)
            return
        padrao = re.compile(re.escape(find_str), re.IGNORECASE)
        idx = self.cbViewTypes.SelectedIndex
        vistos = set()
        for el in self.elementos_escopo:
            try:
                if isinstance(el, TextNote) and idx in [3, 5] and el.Text and padrao.search(el.Text):
                    key = (str(el.Id), "textnote")
                    if key not in vistos:
                        self.itens_encontrados.append(ParametroItem(el, is_text_note=True)); vistos.add(key)
                if idx == 4 and isinstance(el, (View, ViewSheet)) and el.Name and padrao.search(el.Name):
                    key = (str(el.Id), "viewname")
                    if key not in vistos:
                        self.itens_encontrados.append(ParametroItem(el, is_view_name=True)); vistos.add(key)
                if idx in [0, 1, 2, 5]:
                    for p in el.Parameters:
                        if p.StorageType == StorageType.String and not p.IsReadOnly:
                            val = p.AsString()
                            if val and padrao.search(val):
                                key = (str(el.Id), p.Definition.Name, val)
                                if key not in vistos:
                                    self.itens_encontrados.append(ParametroItem(el, param=p)); vistos.add(key)
            except:
                continue
        self.dgResults.ItemsSource = self.itens_encontrados
        self.lblSelectedCount.Text = u"Total: {}".format(len(self.itens_encontrados))
        self.atualizar_preview(None, None)

    def atualizar_preview(self, sender, args):
        find_str = self.tbFind.Text or u""
        replace_str = self.tbReplace.Text or u""
        if find_str:
            padrao = re.compile(re.escape(find_str), re.IGNORECASE)
            for item in self.itens_encontrados:
                if padrao.search(item.CurrentText):
                    item.ProposedText = padrao.sub(replace_str, item.CurrentText)
                    item.Status = u"Válido" if item.ProposedText != item.CurrentText else u"Sem alteração"
                    item.Details = u"Pronto para aplicar." if item.ProposedText != item.CurrentText else u"O valor proposto é igual ao atual."
                else:
                    item.ProposedText = item.CurrentText
                    item.Status = u"Sem alteração"
                    item.Details = u"O texto procurado não corresponde mais."
        for item in self.itens_encontrados:
            if item.param and item.param.IsReadOnly:
                item.Status = u"Somente leitura"
                item.Details = u"O parâmetro não permite edição."
        self.dgResults.Items.Refresh()
        selecionados = len([i for i in self.itens_encontrados if i.IsSelected])
        validos = len([i for i in self.itens_encontrados if i.IsSelected and i.Status == u"Válido"])
        sem_alt = len([i for i in self.itens_encontrados if i.IsSelected and i.Status == u"Sem alteração"])
        leitura = len([i for i in self.itens_encontrados if i.IsSelected and i.Status == u"Somente leitura"])
        conflitos = len([i for i in self.itens_encontrados if i.IsSelected and i.Status not in [u"Válido", u"Sem alteração", u"Somente leitura"]])
        self.lblSummary.Text = u"Total: {}    Válidos: {}    Sem alteração: {}    Somente leitura: {}    Conflitos / Erros: {}".format(selecionados, validos, sem_alt, leitura, conflitos)

    def AoClicarCheckbox(self, sender, args):
        self.atualizar_preview(None, None)

    def selecionar_tudo(self, sender, args):
        for item in self.itens_encontrados:
            item.IsSelected = True
        self.dgResults.Items.Refresh()
        self.atualizar_preview(None, None)

    def limpar_selecao(self, sender, args):
        for item in self.itens_encontrados:
            item.IsSelected = False
        self.dgResults.Items.Refresh()
        self.atualizar_preview(None, None)

    def fechar_janela(self, sender, args):
        self.Close()

    def executar_substituicao(self, sender, args):
        find_str = self.tbFind.Text or u""
        replace_str = self.tbReplace.Text or u""
        if not find_str:
            forms.alert(u"O campo 'Localizar' não pode estar vazio.")
            return
        padrao = re.compile(re.escape(find_str), re.IGNORECASE)
        itens = [i for i in self.itens_encontrados if i.IsSelected and i.Status == u"Válido" and padrao.search(i.CurrentText)]
        if not itens:
            forms.alert(u"Nenhum item válido marcado para alteração. Verifique a coluna Status.")
            return
        if not forms.alert(u"Aplicar as alterações em {} item(ns)?".format(len(itens)), yes=True, no=True):
            return
        t = Transaction(doc, u"OmniBIM - Localizar/Substituir")
        sucessos, erros = 0, 0
        try:
            t.Start()
            for item in itens:
                try:
                    novo = padrao.sub(replace_str, item.CurrentText)
                    if item.param:
                        item.param.Set(novo)
                    elif item.is_text_note:
                        item.element.Text = novo
                    elif item.is_view_name:
                        item.element.Name = novo
                    sucessos += 1
                except Exception as e:
                    erros += 1
                    print(u"Erro no elemento {}: {}".format(item.ItemId, e))
            t.Commit()
        except Exception as e:
            if t.HasStarted() and not t.HasEnded():
                t.RollBack()
            forms.alert(u"A transação foi cancelada: {}".format(e))
            return
        forms.alert(u"Processo concluído.\nAlterações realizadas: {}\nFalhas: {}".format(sucessos, erros))
        self.Close()

try:
    JanelaLocalizarSubstituir('ui.xaml').ShowDialog()
except Exception as ex:
    forms.alert(u"Erro ao carregar a interface XAML: {}".format(ex))
