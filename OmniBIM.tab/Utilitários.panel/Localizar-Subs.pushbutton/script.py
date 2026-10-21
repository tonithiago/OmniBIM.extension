# -*- coding: utf-8 -*-

# ==============================================================================
# 1. METADADOS DO PYREVIT
# Estas variáveis mágicas (__title__ e __docs__) são lidas pelo pyRevit 
# ao carregar a extensão para definir o nome do botão e a dica (tooltip).
# ==============================================================================
__title__ = "Localizar/Substituir"
__docs__ = "Encontra e substitui texto,vista e folhas em um arquivo de projeto aberto." \
"Pesquisa por e substitui texto em notas de texto e grupos de detalhes."

# ==============================================================================
# 2. IMPORTAÇÕES DE BIBLIOTECAS
# ==============================================================================
# Importa todas as classes da API do Revit (View, TextNote, Transaction, etc.)
from Autodesk.Revit.DB import * 
# Importa utilitários do pyRevit para facilitar a criação de janelas (forms) e acesso ao modelo (revit)
from pyrevit import revit, forms
# Importa o módulo CLR (Common Language Runtime) do .NET para integrar Python com C#
import clr
clr.AddReference("System")
from System.Collections.Generic import List
import sys

# ==============================================================================
# 3. VARIÁVEIS DE CONTEXTO DO REVIT
# Capturam o estado atual do software (o que está aberto na tela do usuário).
# ==============================================================================
doc = __revit__.ActiveUIDocument.Document # O banco de dados do projeto ativo
uidoc = __revit__.ActiveUIDocument        # A interface de usuário do projeto ativo
app = __revit__.Application               # A instância do aplicativo Revit

# Importa componentes específicos para montar a janela (interface gráfica) inicial
from rpw.ui.forms import (FlexForm, Label, TextBox, ComboBox, Separator, Button)

# ==============================================================================
# 4. CLASSE AUXILIAR (WRAPPER)
# Criamos esta classe para que a lista de seleção do pyRevit (SelectFromList) 
# mostre um texto amigável (preview) em vez do nome padrão de sistema do objeto.
# O pyRevit sempre procura a propriedade 'name' para exibir na tela.
# ==============================================================================
class ElementoParaRenomear(object):
    def __init__(self, element, preview):
        self.element = element # Armazena o elemento real do Revit (Vista, Folha, etc.)
        self.name = preview    # Armazena o texto formatado que será mostrado na janela

# ==============================================================================
# 5. CONSTRUÇÃO DA INTERFACE DO USUÁRIO (FORMULÁRIO INICIAL)
# Define os campos da primeira janela com a qual o usuário vai interagir.
# ==============================================================================
components = [
    Label('Parâmetro:'), 
    # O ComboBox recebe um dicionário. As chaves (ex: '1. Vistas') são os textos 
    # exibidos ao usuário, e os valores (ex: View) são as Classes reais da API do Revit.
    ComboBox('target', {
            '1. Nome de Vistas': View,        
            '2. Nome de Folhas': ViewSheet,   
            '3. Notas de Textos': TextNote     
        }),
    Separator(),
    Label('Localizar (Texto atual):'), TextBox('txt_find'),
    Label('Substituir por (Novo texto):'), TextBox('txt_replace'),
    Separator(), 
    Button('Buscar Correspondências')
]

# Cria e exibe a janela na tela
form = FlexForm('Padrão de Nomenclatura', components)
form.show()

# Se o usuário fechar a janela no 'X' (cancelar), form.values fica vazio e o script encerra aqui
if not form.values:
    sys.exit()

# Coleta os valores que o usuário digitou/selecionou na janela
find_str = form.values.get('txt_find')
replace_str = form.values.get('txt_replace')
target = form.values.get('target') # Aqui 'target' carrega a classe do Revit (View, ViewSheet ou TextNote)

# Validações básicas de preenchimento
if not find_str:
    forms.alert("O campo 'Localizar' não pode estar vazio.", exitscript=True)
# Se o campo de substituição não foi preenchido, assume uma string vazia (apaga o texto encontrado)
if replace_str is None:
    replace_str = "" 

# ==============================================================================
# 6. BUSCA NO BANCO DE DADOS DO REVIT
# O FilteredElementCollector varre todo o modelo.
# '.OfClass(target)' restringe a busca apenas à classe escolhida (Ex: só pega Vistas).
# '.WhereElementIsNotElementType()' garante que pegamos o elemento em si, não sua família/tipo.
# ==============================================================================
elements_to_process = FilteredElementCollector(doc).OfClass(target).WhereElementIsNotElementType().ToElements()

# Lista vazia que vai guardar apenas os elementos que contêm o texto que estamos procurando
matches = [] 

# ==============================================================================
# 7. FILTRAGEM E PREPARAÇÃO DA PRÉ-VISUALIZAÇÃO
# ==============================================================================
for el in elements_to_process:
    try:
        # Se o elemento tiver a propriedade 'Text' (como um texto simples no Revit), nós a usamos.
        # Caso contrário (como Vistas ou Folhas), nós usamos a propriedade 'Name'.
        current_text = el.Text if hasattr(el, "Text") else el.Name
        
        # Verifica se o que o usuário quer localizar (find_str) existe no nome/texto deste elemento
        if find_str in current_text:
            # Cria a string de visualização: "Texto Antigo  -->  Texto Novo"
            preview = "{}  -->  {}".format(current_text, current_text.replace(find_str, replace_str))
            
            # Empacota o elemento e o texto de preview na nossa classe auxiliar, e joga na lista
            matches.append(ElementoParaRenomear(el, preview))
    except:
        # Se ocorrer algum erro ao tentar ler um elemento específico, apenas ignora e passa para o próximo
        pass

# Se a lista terminou vazia (nada encontrado), avisa o usuário e aborta o script
if not matches:
    forms.alert('Nenhuma correspondência encontrada para "{}" no escopo selecionado.'.format(find_str), exitscript=True)

# ==============================================================================
# 8. JANELA DE CONFIRMAÇÃO (CHECKBOX)
# Abre uma segunda janela nativa do pyRevit que lista os resultados encontrados.
# O usuário pode desmarcar aquilo que não quer que seja renomeado.
# ==============================================================================
elementos_confirmados = forms.SelectFromList.show(
    matches,
    title='Selecione os itens para confirmar a substituição',
    button_name='Substituir Marcados',
    multiselect=True
)

# Se o usuário cancelar essa janela, encerramos a rotina sem fazer nenhuma alteração
if not elementos_confirmados:
    sys.exit() 

# ==============================================================================
# 9. ALTERAÇÃO NO MODELO (TRANSAÇÃO)
# Qualquer alteração (escrita) no Revit DEVE acontecer dentro de uma Transaction.
# Isso garante a integridade do arquivo e cria o histórico de Desfazer (Ctrl+Z).
# ==============================================================================
t = Transaction(doc, 'OmniBIM - Localizar/Substituir')
t.Start() # Inicia a edição do arquivo

# Percorre os itens que o usuário confirmou na janela de listagem
for item in elementos_confirmados:
    el = item.element # Extraímos o elemento real do Revit de dentro do nosso Wrapper
    try:
        # Executa a substituição final de acordo com o tipo do elemento
        if isinstance(el, TextNote):
            el.Text = el.Text.replace(find_str, replace_str)
        else:
            el.Name = el.Name.replace(find_str, replace_str)
    except Exception as e:
        # Se falhar (exemplo: tentar colocar um nome que já existe em outra vista), 
        # imprime o erro no console do pyRevit, mas continua o loop para os demais itens.
        print("Erro ao renomear o elemento {}: {}".format(el.Id, e))

# Confirma, salva e encerra a edição
t.Commit()

# Mensagem visual de encerramento para tranquilizar o usuário
forms.alert("Processo Concluído!")