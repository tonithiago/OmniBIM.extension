# -*- coding: utf-8 -*-

__title__ = "Localizar/Substituir"
__docs__ = "Encontra e substitui texto, vistas e folhas usando uma interface avançada WPF."

from Autodesk.Revit.DB import * 
from pyrevit import revit, forms
import clr
import sys
import re

clr.AddReference("System")

doc = __revit__.ActiveUIDocument.Document

# ==============================================================================
# 1. CLASSES DE DADOS PARA A INTERFACE (BINDING)
# ==============================================================================
class ElementoItem(object):
    def __init__(self, element):
        self.element = element
        self.IsSelected = False
        
        self.ViewName = element.Text if hasattr(element, "Text") else element.Name
        
        # Traduz os tipos internos da API do Revit para a interface do utilizador
        if isinstance(element, TextNote):
            self.ViewType = "Nota de Texto"
        elif isinstance(element, ViewSheet):
            self.ViewType = "Folha"
        elif isinstance(element, ViewSchedule):
            self.ViewType = "Tabela"
        else:
            vt = element.ViewType
            if vt == ViewType.FloorPlan: self.ViewType = "Planta de Piso"
            elif vt == ViewType.CeilingPlan: self.ViewType = "Planta de Teto"
            elif vt == ViewType.EngineeringPlan: self.ViewType = "Planta Estrutural"
            elif vt == ViewType.AreaPlan: self.ViewType = "Planta de Área"
            elif vt == ViewType.ThreeD: self.ViewType = "Vista 3D"
            elif vt == ViewType.Elevation: self.ViewType = "Elevação"
            elif vt == ViewType.Section: self.ViewType = "Corte"
            elif vt == ViewType.DraftingView: self.ViewType = "Vista de Desenho"
            elif vt == ViewType.Legend: self.ViewType = "Legenda"
            else: self.ViewType = str(vt)

class PreviewItem(object):
    def __init__(self, current_name, new_name):
        self.CurrentName = current_name
        self.NewName = new_name

# ==============================================================================
# 2. CLASSE PRINCIPAL DA JANELA (INTERFACE GRÁFICA)
# ==============================================================================
class JanelaLocalizarSubstituir(forms.WPFWindow):
    def __init__(self, xaml_file_name):
        forms.WPFWindow.__init__(self, xaml_file_name)
        
        self.lista_elementos = [] 
        
        self.cbViewTypes.SelectionChanged += self.carregar_elementos
        
        self.tbFind.TextChanged += self.atualizar_tudo
        self.tbReplace.TextChanged += self.atualizar_preview
            
        self.btnSelectAll.Click += self.selecionar_tudo
        self.btnSelectNone.Click += self.limpar_selecao
        self.btnCancel.Click += self.fechar_janela
        self.btnRename.Click += self.executar_renomear
        
        self.carregar_elementos(None, None)

    # -------------------------------------------------------------------------
    # MÉTODOS DE LÓGICA E INTERFACE
    # -------------------------------------------------------------------------
    def AoClicarCheckbox(self, sender, args):
        self.atualizar_preview(None, None)

    def atualizar_tudo(self, sender, args):
        self.filtrar_lista_esquerda(None, None)
        self.atualizar_preview(None, None)

    def carregar_elementos(self, sender, args):
        idx = self.cbViewTypes.SelectedIndex
        self.lista_elementos = []
        
        # Índices do ComboBox conforme o ui.xaml:
        # 0: Todos os Tipos
        # 1: Notas de Texto
        # 2: Plantas 2D
        # 3: Vistas 3D
        # 4: Outras Vistas
        # 5: Tabelas
        # 6: Folhas
        
        # 1. NOTAS DE TEXTO
        if idx in [0, 1]:
            for el in FilteredElementCollector(doc).OfClass(TextNote).WhereElementIsNotElementType().ToElements():
                self.lista_elementos.append(ElementoItem(el))

        # 2. PLANTAS 2D, VISTAS 3D, OUTRAS VISTAS
        if idx in [0, 2, 3, 4]:
            for el in FilteredElementCollector(doc).OfClass(View).WhereElementIsNotElementType().ToElements():
                if el.IsTemplate or isinstance(el, ViewSheet) or isinstance(el, ViewSchedule):
                    continue
                
                vt = el.ViewType
                is_planta = vt in [ViewType.FloorPlan, ViewType.CeilingPlan, ViewType.EngineeringPlan, ViewType.AreaPlan]
                is_3d = (vt == ViewType.ThreeD)
                
                if idx == 0:
                    self.lista_elementos.append(ElementoItem(el))
                elif idx == 2 and is_planta:
                    self.lista_elementos.append(ElementoItem(el))
                elif idx == 3 and is_3d:
                    self.lista_elementos.append(ElementoItem(el))
                elif idx == 4 and not is_planta and not is_3d:
                    self.lista_elementos.append(ElementoItem(el))

        # 3. TABELAS
        if idx in [0, 5]:
            for el in FilteredElementCollector(doc).OfClass(ViewSchedule).WhereElementIsNotElementType().ToElements():
                if not el.IsTemplate:
                    self.lista_elementos.append(ElementoItem(el))
                    
        # 4. FOLHAS
        if idx in [0, 6]:
            for el in FilteredElementCollector(doc).OfClass(ViewSheet).WhereElementIsNotElementType().ToElements():
                self.lista_elementos.append(ElementoItem(el))
        
        self.filtrar_lista_esquerda(None, None)

    def filtrar_lista_esquerda(self, sender, args):
        texto_localizar = self.tbFind.Text.lower()
        
        if not texto_localizar:
            self.lbViews.ItemsSource = self.lista_elementos
            self.lblSelectedCount.Text = "{} carregados".format(len(self.lista_elementos))
        else:
            lista_filtrada = [item for item in self.lista_elementos if texto_localizar in item.ViewName.lower()]
            self.lbViews.ItemsSource = lista_filtrada
            self.lblSelectedCount.Text = "{} filtrados".format(len(lista_filtrada))

    def atualizar_preview(self, sender, args):
        find_str = self.tbFind.Text
        replace_str = self.tbReplace.Text
        lista_preview = []
        
        if find_str: 
            padrao = re.compile(re.escape(find_str), re.IGNORECASE)
            
            for item in self.lista_elementos:
                if item.IsSelected and padrao.search(item.ViewName):
                    novo_nome = padrao.sub(replace_str, item.ViewName)
                    lista_preview.append(PreviewItem(item.ViewName, novo_nome))
        
        self.lbPreview.ItemsSource = lista_preview
        self.lblPreviewCount.Text = "{} correspondências".format(len(lista_preview))

    def selecionar_tudo(self, sender, args):
        itens_visiveis = self.lbViews.ItemsSource
        if itens_visiveis:
            for item in itens_visiveis:
                item.IsSelected = True
            self.lbViews.Items.Refresh()
            self.atualizar_preview(None, None)

    def limpar_selecao(self, sender, args):
        itens_visiveis = self.lbViews.ItemsSource
        if itens_visiveis:
            for item in itens_visiveis:
                item.IsSelected = False
            self.lbViews.Items.Refresh()
            self.atualizar_preview(None, None)

    def fechar_janela(self, sender, args):
        self.Close()

    # -------------------------------------------------------------------------
    # MÉTODO PRINCIPAL: TRANSAÇÃO NO REVIT
    # -------------------------------------------------------------------------
    def executar_renomear(self, sender, args):
        find_str = self.tbFind.Text
        replace_str = self.tbReplace.Text
        
        if not find_str:
            forms.alert("O campo 'Localizar' não pode estar vazio.")
            return
            
        padrao = re.compile(re.escape(find_str), re.IGNORECASE)
        
        itens_para_processar = [item for item in self.lista_elementos if item.IsSelected and padrao.search(item.ViewName)]
        
        if not itens_para_processar:
            forms.alert("Nenhum item marcado contém o texto procurado.")
            return

        t = Transaction(doc, 'OmniBIM - Localizar/Substituir')
        t.Start()
        
        sucessos = 0
        for item in itens_para_processar:
            el = item.element
            try:
                novo_nome_final = padrao.sub(replace_str, item.ViewName)
                
                if isinstance(el, TextNote):
                    el.Text = novo_nome_final
                else:
                    el.Name = novo_nome_final
                sucessos += 1
            except Exception as e:
                print("Erro ao renomear o elemento {}: {}".format(el.Id, e))
                
        t.Commit()
        
        self.Close()
        forms.alert("Processo Concluído!\n{} itens renomeados com sucesso.".format(sucessos))

# ==============================================================================
# 3. INICIALIZAÇÃO
# ==============================================================================
try:
    JanelaLocalizarSubstituir('ui.xaml').ShowDialog()
except Exception as ex:
    forms.alert("Erro ao carregar a interface XAML: {}".format(ex))