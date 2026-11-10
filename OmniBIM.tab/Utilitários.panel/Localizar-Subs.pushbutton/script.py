# -*- coding: utf-8 -*-
__title__ = "Localizar/Substituir"
__docs__ = "Localiza e substitui parâmetros de texto, notas, vistas e folhas com pré-visualização em tabela."

import clr
clr.AddReference("System")
clr.AddReference("WindowsBase")
clr.AddReference("PresentationCore")
clr.AddReference("PresentationFramework")

import re
from Autodesk.Revit.DB import *
from pyrevit import revit, forms
import time as _time
from System import TimeSpan
from System.Collections.Generic import List
from System.Windows.Threading import DispatcherTimer
from System.Windows.Input import Mouse, Cursors

doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument

# ---------------------------------------------------------------------------
# CONFIGURAÇÕES
# ---------------------------------------------------------------------------
LIMITE_RESULTADOS = 2000      # máximo de linhas exibidas/alteradas por busca
ATRASO_DIGITACAO_MS = 350     # tempo (ms) após parar de digitar para disparar a busca
ORCAMENTO_MS_POR_TICK = 40    # tempo máximo (ms) de indexação por fatia; menor = janela mais fluida

# Nomes de parâmetros ignorados. Use o nome NORMALIZADO:
# minúsculo, sem espaços, "_", "-" ou ".". Ex.: "Ifc GUID" -> u"ifcguid"
PARAMS_IGNORADOS_NOMES = set([
    u"ifcguid",
    u"typeifcguid",
])


def _bip(nome):
    """Obtém um BuiltInParameter pelo nome sem quebrar se não existir nesta versão do Revit."""
    return getattr(BuiltInParameter, nome, None)


# Parâmetros nativos ignorados
BIPS_IGNORADOS = set(b for b in (
    _bip("IFC_GUID"),
    _bip("IFC_TYPE_GUID"),
) if b is not None)


# ---------------------------------------------------------------------------
# FUNÇÕES AUXILIARES
# ---------------------------------------------------------------------------
def _normalizar(nome):
    return re.sub(r"[\s_\-\.]", u"", nome or u"").lower()


def parametro_relevante(p):
    """True apenas para parâmetros de texto, editáveis e que façam sentido alterar."""
    try:
        if p.StorageType != StorageType.String or p.IsReadOnly:
            return False
        d = p.Definition
        if d is None:
            return False
        if _normalizar(d.Name) in PARAMS_IGNORADOS_NOMES:
            return False
        try:
            # Só existe em InternalDefinition (parâmetros nativos)
            if d.BuiltInParameter in BIPS_IGNORADOS:
                return False
        except AttributeError:
            pass  # ExternalDefinition (parâmetro compartilhado)
        return True
    except:
        return False


def obter_id_int(el):
    try:
        return el.Id.IntegerValue
    except:
        return el.Id.Value


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


# ---------------------------------------------------------------------------
# ITEM DA TABELA
# ---------------------------------------------------------------------------
class ParametroItem(object):
    """Linha da tabela de pré-visualização; mantém a referência ao elemento/parâmetro Revit."""
    def __init__(self, element, param=None, is_text_note=False, is_view_name=False):
        self.element = element
        self.param = param
        self.is_text_note = is_text_note
        self.is_view_name = is_view_name
        self.IsSelected = True
        self.ItemId = str(obter_id_int(element))
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


# ---------------------------------------------------------------------------
# JANELA
# ---------------------------------------------------------------------------
class JanelaLocalizarSubstituir(forms.WPFWindow):
    def __init__(self, xaml_file_name):
        forms.WPFWindow.__init__(self, xaml_file_name)
        self.elementos_escopo = []
        self.itens_encontrados = []
        self.indice = []  # lista de (tipo, elemento, parametro, texto)
        self.ids_modelo = []
        self.gerador_indice = None
        self.indexando = False
        self.total_indice = 0
        self.processados = 0

        # Timers de "debounce": só executam quando o usuário para de digitar
        self.timer_busca = self._criar_timer(self._tick_busca)
        self.timer_preview = self._criar_timer(self._tick_preview)

        # Timer da indexação em fatias (prioridade Background: a interface tem preferência)
        self.timer_indice = DispatcherTimer()
        self.timer_indice.Interval = TimeSpan.FromMilliseconds(1)
        self.timer_indice.Tick += self._tick_indice

        self.cbViewTypes.SelectionChanged += self.ao_mudar_escopo
        self.tbFind.TextChanged += self.agendar_busca
        self.tbReplace.TextChanged += self.agendar_preview
        self.btnSelectAll.Click += self.selecionar_tudo
        self.btnSelectNone.Click += self.limpar_selecao
        self.btnLocate.Click += self.localizar_no_revit
        self.btnCancel.Click += self.fechar_janela
        self.btnRename.Click += self.executar_substituicao
        self.Loaded += self.ao_carregar_janela
        self.Closed += self.ao_fechar_janela

    # ----- timers / debounce -------------------------------------------------
    def _criar_timer(self, callback):
        t = DispatcherTimer()
        t.Interval = TimeSpan.FromMilliseconds(ATRASO_DIGITACAO_MS)
        t.Tick += callback
        return t

    def agendar_busca(self, sender, args):
        self.timer_busca.Stop()
        self.timer_busca.Start()

    def _tick_busca(self, sender, args):
        self.timer_busca.Stop()
        self.atualizar_busca(None, None)

    def agendar_preview(self, sender, args):
        self.timer_preview.Stop()
        self.timer_preview.Start()

    def _tick_preview(self, sender, args):
        self.timer_preview.Stop()
        self.atualizar_preview(None, None)

    # ----- eventos da tabela -------------------------------------------------
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

    # ----- escopo e indexação em fatias --------------------------------------
    def ao_carregar_janela(self, sender, args):
        # A janela já está visível; a indexação roda em fatias curtas
        self.iniciar_indexacao()

    def ao_fechar_janela(self, sender, args):
        # Evita que timers disparem (e chamem a API do Revit) depois que a janela fechou
        self.timer_indice.Stop()
        self.timer_busca.Stop()
        self.timer_preview.Stop()

    def ao_mudar_escopo(self, sender, args):
        self.iniciar_indexacao()
        self.atualizar_busca(None, None)

    def iniciar_indexacao(self):
        self.timer_indice.Stop()
        self.carregar_escopo()
        self.indice = []
        self.processados = 0
        self.total_indice = len(self.elementos_escopo) + len(self.ids_modelo)
        self.gerador_indice = self._gerar_indice()
        self.indexando = True
        self.timer_indice.Start()

    def _tick_indice(self, sender, args):
        limite = _time.time() + ORCAMENTO_MS_POR_TICK / 1000.0
        try:
            while _time.time() < limite:
                next(self.gerador_indice)
                self.processados += 1
        except StopIteration:
            self.timer_indice.Stop()
            self.indexando = False
            self.atualizar_busca(None, None)
            return
        if not (self.tbFind.Text or u""):
            self.lblSelectedCount.Text = u"Indexando... {}%  (você já pode digitar)".format(self._percentual())

    def _percentual(self):
        if not self.total_indice:
            return 0
        return int(100.0 * self.processados / self.total_indice)

    def _sufixo_progresso(self):
        if not self.indexando:
            return u""
        return u"  |  indexando {}% (resultado parcial)".format(self._percentual())

    def carregar_escopo(self):
        idx = self.cbViewTypes.SelectedIndex
        self.elementos_escopo = []
        self.ids_modelo = []
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
            # Apenas os Ids (rápido). Os elementos são abertos aos poucos durante a indexação.
            self.ids_modelo = list(FilteredElementCollector(doc).WhereElementIsNotElementType().ToElementIds())

    def _modelo_valido(self, el, idx):
        try:
            if el is None or el.Category is None:
                return False
            if el.Category.CategoryType != CategoryType.Model:
                return False
            if idx == 0:
                try:
                    cid = el.Category.Id
                    if cid == ElementId(BuiltInCategory.OST_PropertySet) or cid == ElementId(BuiltInCategory.OST_MaterialAssets):
                        return False
                except:
                    pass
            return True
        except:
            return False

    def _gerar_indice(self):
        """Gerador: cada 'yield' marca um elemento processado; o timer retoma em fatias."""
        idx = self.cbViewTypes.SelectedIndex
        vistos = set()
        for el in self.elementos_escopo:
            self._indexar_elemento(el, idx, vistos)
            yield
        for eid in self.ids_modelo:
            el = doc.GetElement(eid)
            if self._modelo_valido(el, idx):
                self._indexar_elemento(el, idx, vistos)
            yield

    def _indexar_elemento(self, el, idx, vistos):
        try:
            if idx in [3, 5] and isinstance(el, TextNote) and el.Text:
                self.indice.append(("textnote", el, None, el.Text))

            if idx == 4 and isinstance(el, (View, ViewSheet)) and el.Name:
                self.indice.append(("viewname", el, None, el.Name))

            if idx in [0, 1, 2, 5]:
                eid = obter_id_int(el)
                for p in el.Parameters:
                    if not parametro_relevante(p):
                        continue
                    val = p.AsString()
                    if not val:
                        continue
                    key = (eid, p.Definition.Name, val)
                    if key in vistos:
                        continue
                    vistos.add(key)
                    self.indice.append(("param", el, p, val))
        except:
            pass

    # ----- busca e pré-visualização -----------------------------------------
    def atualizar_busca(self, sender, args):
        find_str = self.tbFind.Text or u""
        self.itens_encontrados = []
        if not find_str:
            self.dgResults.ItemsSource = self.itens_encontrados
            self.lblSelectedCount.Text = u"Digite o texto para localizar" + self._sufixo_progresso()
            self.atualizar_preview(None, None)
            return

        padrao = re.compile(re.escape(find_str), re.IGNORECASE)
        truncado = False
        for tipo, el, p, texto in self.indice:
            if not padrao.search(texto):
                continue
            if len(self.itens_encontrados) >= LIMITE_RESULTADOS:
                truncado = True
                break
            try:
                if tipo == "textnote":
                    self.itens_encontrados.append(ParametroItem(el, is_text_note=True))
                elif tipo == "viewname":
                    self.itens_encontrados.append(ParametroItem(el, is_view_name=True))
                else:
                    self.itens_encontrados.append(ParametroItem(el, param=p))
            except:
                continue

        self.dgResults.ItemsSource = self.itens_encontrados
        txt = u"Total: {}".format(len(self.itens_encontrados))
        if truncado:
            txt += u" (limitado a {} — refine a busca)".format(LIMITE_RESULTADOS)
        self.lblSelectedCount.Text = txt + self._sufixo_progresso()
        self.atualizar_preview(None, None)

    def atualizar_preview(self, sender, args):
        find_str = self.tbFind.Text or u""
        replace_str = self.tbReplace.Text or u""
        padrao = re.compile(re.escape(find_str), re.IGNORECASE) if find_str else None

        for item in self.itens_encontrados:
            if padrao:
                if padrao.search(item.CurrentText):
                    item.ProposedText = padrao.sub(replace_str, item.CurrentText)
                    if item.ProposedText != item.CurrentText:
                        item.Status = u"Válido"
                        item.Details = u"Pronto para aplicar."
                    else:
                        item.Status = u"Sem alteração"
                        item.Details = u"O valor proposto é igual ao atual."
                else:
                    item.ProposedText = item.CurrentText
                    item.Status = u"Sem alteração"
                    item.Details = u"O texto procurado não corresponde mais."
            if item.param and item.param.IsReadOnly:
                item.Status = u"Somente leitura"
                item.Details = u"O parâmetro não permite edição."

        self.dgResults.Items.Refresh()

        # Contagem em uma única passagem
        selecionados = validos = sem_alt = leitura = conflitos = 0
        for i in self.itens_encontrados:
            if not i.IsSelected:
                continue
            selecionados += 1
            if i.Status == u"Válido":
                validos += 1
            elif i.Status == u"Sem alteração":
                sem_alt += 1
            elif i.Status == u"Somente leitura":
                leitura += 1
            else:
                conflitos += 1
        self.lblSummary.Text = u"Total: {}    Válidos: {}    Sem alteração: {}    Somente leitura: {}    Conflitos / Erros: {}".format(
            selecionados, validos, sem_alt, leitura, conflitos)

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

    # ----- aplicação ---------------------------------------------------------
    def executar_substituicao(self, sender, args):
        # Garante que a pré-visualização reflete o que está nos campos agora
        self.timer_indice.Stop()
        self.timer_busca.Stop()
        self.timer_preview.Stop()
        self.atualizar_preview(None, None)

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

''
try:
    JanelaLocalizarSubstituir('ui.xaml').ShowDialog()
except Exception as ex:
    forms.alert(u"Erro ao carregar a interface XAML: {}".format(ex))