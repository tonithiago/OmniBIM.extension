# TOPOBIM para pyRevit — Revit 2026

Conversão do pacote C# preservado em `bruto_para_coverter`. O botão funciona
com IronPython 2.7.12 e os componentes WPF do pyRevit, sem DLL TOPOBIM,
SDK .NET, pip ou execução dos instaladores do pacote original.

## Interface

O tema monocromático fica centralizado em `TopoBimTheme.xaml`, compartilhado pela
janela principal e pela janela de ocorrências. Usa os controles WPF existentes,
Segoe UI, abas planas, foco visível, ações secundárias brancas e ação principal preta.
O visualizador e o resumo dividem a largura na proporção 65/35; o rodapé permanece
fora da área rolável. A janela ajusta seu tamanho inicial à área de trabalho do Windows.
Importação, coordenadas, aferições 2D e criação mantêm os mesmos cálculos e eventos.

Validação visual isolada: 91 testes de núcleo/adaptadores, testes de eventos e
controles WPF e imagens em 96, 120 e 144 DPI, com janelas amplas e compactas.
As imagens usam o CSV de exemplo do repositório, sem substituir dados do usuário.
Essas verificações usam um host simulado: não validam a execução dentro do Revit
nem a troca entre monitores físicos com DPI diferente. A configuração do botão
continua exclusiva para Revit 2026; suporte a 2025 não foi habilitado por esta mudança.

## Usar

Se o pyRevit carregar uma cópia em `AppData`, atualize essa instalação a partir
da raiz deste repositório com `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Atualizar-TopoBIM.ps1`.
O comando sincroniza apenas os arquivos deste botão, verifica as cópias por SHA256
e guarda os arquivos anteriores em `%LOCALAPPDATA%/OmniBIM/backups`.
Recarregar o pyRevit sozinho não copia alterações da pasta do GitHub para `AppData`.

1. Recarregue a extensão pelo **Reload** do pyRevit, ou reinicie o Revit 2026.
2. Abra um projeto com nível e tipo de sólido topográfico.
3. Acesse **OmniBIM > Utilitários > TOPOBIM**.
4. Em **Entrada**, selecione CSV/TXT UTF-8 ou um DWG já vinculado/importado.
   Confira separador, unidade, cabeçalho e colunas antes de ler.
5. Em **Conferência**, escolha e aplique as camadas do DWG. Nenhuma camada é
   selecionada automaticamente. Confira pontos, cotas, prévia e ocorrências.
   Em **Visualização do terreno**, alterne entre **Planta** e **Modelo 3D**.
   No 3D, arraste para girar, use Shift + arraste para deslocar e a roda para zoom.
   **Enquadrar** ou duplo clique restaura a vista inicial. A superfície é ilustrativa,
   em escala real, com triangulação própria e até 1.400 pontos na prévia; o Revit
   define a triangulação final. Todos os pontos aceitos continuam na criação.
   Em **Aferições do terreno**, as células **Distância**, **Área** e **Cota de nível**
   selecionam exclusivamente vértices originais na vista **Planta**. Iniciar uma
   aferição muda automaticamente para 2D. Distância usa dois pontos e mostra a
   distância horizontal Este/Norte, sem incluir o desnível. Área usa três ou mais vértices, fechados com
   **Concluir área**, e informa a projeção horizontal em m². Cota informa o Z na
   referência do levantamento, sem interpolação. O cursor destaca o vértice antes
   da seleção e mostra suas coordenadas. Cliques sem vértice próximo são rejeitados;
   quando dois pontos não podem ser distinguidos na tela, aumente o zoom. Todos os
   vértices aceitos participam da seleção, independentemente da amostragem visual.
   Os cálculos usam as coordenadas originais, sem arredondamento intermediário.
   O resultado mostra três casas decimais e sua dica mostra seis; a exatidão depende
   do levantamento de origem. O modo 3D permanece disponível para visualização.
   Arrastar continua navegando, sem adicionar pontos. **Desfazer ponto**, **Limpar**
   e **Navegar** permitem corrigir ou encerrar a seleção; Esc também volta à navegação.
   Alterar ou reler a origem limpa as aferições para evitar resultados antigos.
   Para modelar pavimentação, ative **Criar pisos nas áreas fechadas do DWG**,
   selecione o DWG e o modo de coordenadas, e clique **Identificar áreas de piso**.
   Marque os layers desejados, escolha o tipo de piso de cada layer e o nível
   de referência dos pisos. A lista mostra os materiais e a espessura dos tipos
   existentes no projeto. Isso também funciona com terreno vindo de CSV.
   O padrão é **Georreferenciar pelos vértices comuns do levantamento**. Leia o
   levantamento primeiro. O plugin relaciona as curvas do DWG ao CSV e mostra
   o layer e o percentual de correspondência antes da criação.
6. Em **Criação**, escolha tipo, nível e posicionamento. Confira a latitude e
   longitude calculadas a partir da origem UTM ou informe-as manualmente.
   Confirme a atualização de **Terreno Padrão** e o alinhamento dos pontos base.
   Se estiver redefinindo E/N/Z, confirme também a troca das coordenadas compartilhadas.
7. Salve o relatório JSON pelo botão disponibilizado após a criação.
   Use **Ver pisos em 3D** para enquadrar terreno e pisos na vista de conferência.
   Pisos nas cotas do levantamento podem ficar acima da faixa visível de uma
   planta do nível zero, sem que isso signifique falha de criação.

O pacote original continua independente. Este botão não instala, desinstala nem
desativa um complemento C# previamente instalado.

## Regras preservadas e ajustes

- Metros, centímetros, milímetros e pés; separadores `;`, vírgula e tabulação.
  Cabeçalhos reconhecidos ajustam automaticamente as colunas; sem reconhecimento,
  confira manualmente. Decimal com vírgula requer separador `;` ou tabulação.
- Grade XY de 1 mm com arredondamento equivalente a `Math.Round(double, 3)`.
  A primeira cota é mantida: diferenças até 1 mm são duplicados; maiores são
  avisos aceitos. Não se calcula média. Erros de leitura/geometria bloqueiam a criação.
- A janela de ocorrências mostra toda a lista, permite exportar CSV com BOM e
  reler a origem, mesmo quando faltam pontos para formar um terreno.
- Máximo de 100.000 registros de entrada, incluindo linhas inválidas, ou vértices
  CAD; máximo de 20.000 pontos únicos para criar. A prévia desenha até 3.000 pontos,
  mas não remove pontos da criação. Limite conservador: 15 km da origem interna.
- Coordenadas compartilhadas existentes, inclusive rotação e deslocamento
  vertical válidos, são respeitadas. Uma origem vertical diferente de zero não
  dispara a troca de localização. Quando necessário, sugere-se uma nova origem
  no centro E/N, Z=0 e rotação zero, com confirmação explícita.
- A localização **Terreno Padrão** é reutilizada e ativada em toda criação. Suas coordenadas
  recebem a transformação atual ou os novos E/N/Z informados. Não são criados
  nomes TOPOBIM com data. Todas as localizações TOPOBIM anteriores, ativas ou
  inativas, são removidas após a substituição; outras localizações nomeadas são preservadas.
- Ponto base do projeto e ponto de levantamento ficam coincidentes sobre a
  superfície do sólido, em X=0/Y=0 internos, com a cota real do terreno nessa
  posição. A altura é calculada na face superior após conferir as cotas do sólido;
  não utiliza a face inferior nem força Z=0. A origem interna e a referência
  vertical compartilhada continuam independentes da cota dos marcadores. Movem-se apenas
  os marcadores, com o ponto de levantamento temporariamente desacoplado.
  Os estados fixado/desacoplado anteriores são restaurados, e a transformação
  compartilhada é conferida novamente. As cotas do levantamento não são zeradas.
  Se a origem em planta estiver fora do terreno, a operação pede para redefinir
  Este/Norte próximos do centro do levantamento, em vez de inventar uma cota.
- Latitude e longitude são calculadas da origem UTM para **SIRGAS 2000 (GRS80)**
  ou **WGS 84**, usando zona e hemisfério informados. A inversão UTM mantém o
  datum declarado, sem transformação entre datums. Para coordenadas locais ou
  outros datums, informe latitude/longitude conhecidas manualmente; não se
  deduz uma posição geográfica de coordenadas locais. Valores são mostrados em
  graus e gravados em radianos na `SiteLocation` do Revit. O Revit recalcula o
  fuso horário ao atualizar essas propriedades; confira-o na aba Localização.
- Localização, dados geográficos, pontos base, terreno e pisos opcionais fazem parte da mesma operação.
  Os pontos são alinhados por último e conferidos novamente após o Commit;
  um TransactionGroup mantém a operação reversível até essa conferência e reúne
  tudo em um único Desfazer. Os vértices reais da
  superfície são conferidos com tolerância de 1 mm; deslocamento vertical
  uniforme pode ser corrigido. Falhas revertem a operação inteira.
- Alterar origem, colunas, unidade, modo CAD ou camadas invalida a análise.
  Alterar parâmetros de criação invalida as confirmações. Falha de exportação
  após criar não é apresentada como falha da criação.
- Terreno: sem reprojeção dos pontos de entrada, geóide, divisas côncavas, furos ou linhas de quebra.
- DWG: curvas, polilinhas, pontos, malhas e blocos aninhados; modos WCS original
  e posição compartilhada atual. Sem interpretação de textos ou proxies Civil 3D.

## Pisos sobre o terreno

- Cria elementos nativos **Piso**, um por área fechada, com o tipo e nível escolhidos.
  O material vem da estrutura composta do tipo; o plugin não modifica tipos existentes.
- Lê polilinhas fechadas e reúne curvas conectadas do mesmo layer, inclusive em
  blocos aninhados. Contornos côncavos, ilhas e furos são preservados nos pisos.
  Curvas são aproximadas pelos segmentos de `Tessellate` do Revit. Contornos
  com cotas Z no WCS do DWG definem a face superior, com interpolação linear por
  triângulos. Contornos inteiramente em Z=0 são tratados como 2D e usam o terreno.
  A translação vertical do vínculo e das coordenadas compartilhadas não conta
  como uma cota presente no arquivo original.
- Curvas abertas/ramificadas e contornos inválidos são apresentados na conferência.
  Nenhum layer ou tipo de piso é escolhido automaticamente. O DWG precisa ser de modelo.
- A face **superior** do piso atinge as cotas de projeto do DWG ou do terreno.
  A espessura desenvolve-se para baixo. O piso escava o Toposolid pela operação
  nativa `ExcavateBy` onde há interseção. A superfície de referência é guardada
  antes de escavar, para que o corte não altere as cotas usadas na conferência.
- Nível e deslocamento vertical são definidos explicitamente, inclusive com nível
  diferente de zero e coordenadas compartilhadas com rotação/deslocamento vertical.
  O topo é medido na geometria física, antes e após confirmar a transação, com
  tolerância de 1 mm. Falha de conformação reverte também o terreno e a localização.
- Tipos com camada de espessura variável são permitidos, inclusive com base plana.
  A base não é mais exigida na conferência. Se a malha da face superior não estiver
  disponível na regeneração, seus vértices reais de edição da forma são conferidos.
  Se também faltarem os vértices, a operação informa o elemento que não pôde ser validado.
  O Revit pode emitir seu aviso nativo de imprecisão de espessura em pisos conformados;
  o plugin não suprime esse aviso. O tipo mantém sua espessura nominal.
- Limites dos pisos: 2.500 vértices por contorno CAD, 5.000 pontos de conformação por
  área e tolerância nativa de comprimento de curvas. Simplifique/divida áreas maiores.
  Áreas parcialmente ou totalmente fora da superfície são permitidas, mantendo
  o contorno completo. Pontos externos usam a cota interpolada na borda mais próxima
  como referência de modelagem; não representam cotas medidas nem apoio no levantamento.
  A conformação interpola entre esses pontos na parte externa, sem prolongar o declive
  indefinidamente. A validação do topo usa 1 mm na superfície de referência e nos
  pontos de controle externos. O relatório registra origem das cotas, resultado
  da escavação, pontos externos e o alcance da validação.
  A superfície medida continua com ajuste numérico de borda limitado a 0,1 mm.
  O relatório também registra pisos, layers, tipos, níveis e erros medidos.
- O DWG é relido antes de alterar a localização; contornos modificados desde a
  conferência bloqueiam a criação. Alterar a origem dos pisos exige nova identificação;
  alterar layers, tipos ou nível invalida as confirmações.
- No modo padrão, os vértices comuns determinam uma transformação rígida XY
  do DWG para as coordenadas do levantamento. Pelo menos 95% dos pontos devem
  coincidir dentro de 2 mm, com seis pontos distintos não colineares. Ajustes
  ambíguos são recusados. Não há escala, alteração das cotas DWG ou ajuste por
  simples centralização das áreas. Os pisos passam pela mesma conversão para
  a localização compartilhada final usada pelo terreno. A transformação,
  cobertura e layer de referência ficam no relatório e nos comentários.
  As opções manuais WCS e posição atual continuam disponíveis; nesta última,
  a posição interna do vínculo é preservada mesmo ao trocar a localização.
- A seleção após criar inclui os pisos, além do terreno. A vista 3D de conferência
  é criada na mesma transação, com enquadramento dos resultados, sem DWG/anotações
  e sem outros pisos/terrenos do projeto. Um único Desfazer reverte essa operação.
  O botão de visualização abre essa vista depois de fechar a janela do TOPOBIM.

## Organização

- `script.py` / `bundle.yaml`: entrada e disponibilidade do botão, apenas 2026.
- `topobim_core.py`: dados `Point`, `ReadResult`, `Analysis`, leitura, validação,
  contorno, estatísticas e exportações; sem dependência do Revit.
- `topobim_revit.py`: DWG, unidades, transformações, transação e `Toposolid`.
- `topobim_geo.py`: inversão UTM de sexta ordem e validação de latitude/longitude,
  sem dependências externas no botão.
- `topobim_floor_geometry.py`: contornos, furos, interseções e amostragem de malhas,
  sem dependência do Revit.
- `topobim_floors.py`: leitura de áreas do DWG, tipos/materiais, criação e conferência dos pisos.
- `topobim_ui.py`, `TopoBim.xaml`, `Occurrences.xaml`: interface modal e prévia.
- `tests`: regressões do núcleo, verificações WPF e teste de integração Revit.

O serviço de criação recebe análise, IDs de tipo/nível, configurações e origem;
retorna o ID criado e o relatório somente após `Commit` confirmado. As operações
Revit executam na thread do comando; não há janela modeless nem transação mantida
aberta durante a conferência do usuário.

## Validação executada

- 79 testes do núcleo, cálculo geográfico, geometria de pisos e adaptadores com documento simulado passaram em CPython e no IronPython 2.7.12 do pyRevit,
  hospedado separadamente em .NET Framework 4.8.
- Pisos externos: testes automatizados cobrem áreas parcialmente/totalmente fora,
  coordenadas muito distantes sem expansão da grade de busca, referência da borda
  sem prolongamento do declive e manutenção da conferência de apoio na sobreposição.
  A continuidade externa também foi ensaiada dentro do Revit, conforme abaixo.
- WPF real: carregamento dos dois XAML, bindings, navegação, leitura dos exemplos,
  seleção de camadas simulada, tipos de piso e caixas de seleção na tabela, bloqueios,
  invalidação das confirmações e renderização. Os dados do Revit são simulados nesse teste.
- 804 comparações de arredondamento com `System.Math.Round`, incluindo UTM.
- Inversão UTM comparada com PROJ em 2.160 coordenadas (60 zonas, dois elipsoides,
  ambos os hemisférios). Maior diferença numérica observada: 5,7 × 10⁻¹⁴ graus.
  Isso valida o cálculo; a localização correta depende do datum, zona, hemisfério
  e coordenadas fornecidos pelo levantamento.
- Exemplo de terreno: 54 pontos, 50 × 80 m, cotas 12,000 a 14,773 m.
- Exemplo de erros: conflito em E=100/N=100 e erro de leitura na linha 7.
- Caso verificado no Revit 2026.5/.NET 10: após criar o sólido do exemplo,
  ambos os pontos terminaram em Z=13,1485 m, coincidentes (distância 0 m).
  O ensaio usou um documento temporário; o projeto aberto manteve seus pontos.
- Histórico anterior, com apoio pela face inferior, no Revit 2026.5/.NET 10: quatro casos de criação/conferência da geometria
  passaram em documento independente: plano inclinado, mudança de declive e contorno
  com furo, mais um tipo de 30 cm com nível em -4 m. Nos três primeiros, o nível
  de referência ficou em +3 m; os pisos permaneceram nas cotas do terreno (~11 a 13 m).
  Maior diferença de apoio observada, antes e após Commit: 0,000582 mm.
  Todos os elementos foram revertidos. O ensaio registra os avisos nativos no resultado
  e os remove somente do documento temporário para não bloquear a execução automática.
  Script: `tests/verify_floors_revit.py`. A extração do DWG real continua a exigir
  conferência interativa; transformações CAD foram verificadas com adaptador simulado.
- Versão 0.8 no Revit 2026.5/.NET 10: sete casos passaram com conferência da face
  superior antes/após Commit e escavação nativa confirmada: plano inclinado, relevo,
  furo, tipo de 30 cm, tipo com camada variável/base plana, cotas Z do contorno e
  piso que ultrapassa o terreno. Maior erro de cota observado: 0,000582 mm.
  Todos os elementos foram revertidos em documento temporário independente.
  A importação do DWG real do usuário não faz parte desse ensaio.
- Versão 0.8.1: oito casos nativos passaram antes/após Commit, incluindo piso
  inteiramente externo a 10 km do terreno, sem escavação. Os sólidos temporários
  são transladados para perto da origem antes da triangulação, e as coordenadas
  originais são restituídas somente na leitura dos vértices; o modelo não é movido.
  Isso evita perda de precisão da malha em coordenadas grandes. Quando a malha
  não cobre um ponto de controle do piso, seus vértices reais são conferidos,
  sem confundir a cobertura da malha do piso com o limite do terreno.
  O teste automatizado reproduz também as coordenadas do aviso de piso externo.
  O botão solicita engine Python limpa; após atualizar, use **pyRevit > Reload**.
- Versão 0.8.2: os oito casos nativos passaram, incluindo a criação da vista 3D.
  Um teste adicional usou as 64 áreas dos layers selecionados no DWG real do
  projeto aberto: todas foram criadas, escavadas quando aplicável e conferidas
  após Commit em documento temporário, depois revertidas. A prévia confirmou
  coordenadas próximas do vínculo, em vez de deslocamento de milhões de metros.
  Script reproduzível para um projeto com um lote TOPOBIM e seu DWG disponível:
  `tests/verify_existing_dwg.py`. O teste lê o projeto original e cria somente
  em um documento independente. Tipos de piso de QA são genéricos de 150 mm.
  Esse teste não altera nem reposiciona pisos antigos do projeto original.

**Ensaio de integração completo ainda pendente:** o teste no console do Revit
2026.5/.NET 10 foi bloqueado por um aviso de sobreposição entre sólidos temporários.
Os casos foram isolados no script para evitar essa sobreposição numa nova execução.
Os testes isolados de WPF usam um host simulado. Extração de DWG e Desfazer
também exigem conferência dentro do Revit.

Para repetir os testes do núcleo a partir da pasta do botão:

```powershell
python -B -m unittest discover -s tests -v
```

Para as verificações isoladas IronPython/WPF, use Windows PowerShell em STA e
informe uma biblioteca padrão IronPython 2.7.12 já disponível localmente:

```powershell
powershell.exe -NoProfile -STA -File tests/run_ironpython.ps1 -StandardLibrary C:/caminho/Lib -RenderDirectory C:/Temp/topobim-preview
```

Esse recurso é apenas para desenvolvimento; o botão utiliza o ambiente do pyRevit.

## Aceite dentro do Revit

Use um projeto descartável com um tipo de Toposolid de estrutura composta e um
nível. No console IronPython do pyRevit, em contexto de API e sem transação aberta,
execute `tests/verify_revit.py` com `__file__` apontando para esse arquivo e
`__name__='__main__'`. Exemplo, após definir `path` com o caminho absoluto:

```python
execfile(path, {'__file__': path, '__name__': '__main__'})
```

O script testa diferentes espessuras e níveis, rotação, referência vertical,
substituição de Terreno Padrão, coincidência dos pontos base na cota da superfície, latitude/longitude,
vértice ausente e rollback após falha inclusive dos dados geográficos. Um `TransactionGroup`
reverte todos os elementos e localizações temporários, inclusive em caso de erro.
Não execute dentro de outro wrapper que abra uma transação.

Complete também os ensaios interativos:

1. Recarregue o pyRevit, abra o botão e crie a partir do CSV de exemplo. Confira
   coordenadas e cotas em pontos conhecidos, incluindo mínimo e máximo.
2. Confira **Gerenciar > Localização > Localização/Terreno**: latitude/longitude
   devem corresponder à origem informada, e **Terreno Padrão** deve estar atual,
   sem entradas TOPOBIM antigas acumuladas após criações sucessivas.
   Confira os dois pontos base coincidentes sobre a superfície e seus E/N/Z compartilhados;
   a cota deve corresponder ao terreno na posição dos marcadores.
   Use **Desfazer**: sólido, localização, latitude/longitude e pontos base devem ser revertidos juntos.
3. Feche/cancele a janela antes de criar: nenhuma alteração deve permanecer.
4. Leia um DWG com pontos de controle conhecidos, transladado/rotacionado e com
   blocos aninhados. Compare WCS original e coordenadas compartilhadas atuais.
   Verifique seleção múltipla de camadas, DWG restrito à vista e ausência de geometria.
5. Teste zoom, arraste, enquadramento, troca de origem, releitura e exportações.
6. Corrija o arquivo de erros e releia: o aviso de cota pode permanecer, mas o erro
   de leitura precisa desaparecer antes de liberar a criação.
7. Em Conferência, identifique os layers de pavimentação de um DWG conhecido.
   Confira áreas/furos, materiais, nível associado, cota superior e escavação em
   cortes. Teste com origem compartilhada deslocada/rotacionada e terreno via CSV.
   Confira que cancelar ou um erro em um piso reverte a operação inteira e que
   um único Desfazer reverte terreno, pisos, localização e pontos base.

Referências: [Toposolid.Create — Autodesk](https://help.autodesk.com/cloudhelp/2026/ENU/Revit-API-MainReference/files/html/fb528545-b035-bfe2-71da-88baa9a979ff.htm)
e [WPFWindow — pyRevit](https://docs.pyrevitlabs.io/reference/pyrevit/forms/_ipy/).
Georreferenciamento: [UTM — PROJ](https://proj.org/en/stable/operations/projections/utm.html),
[Transverse Mercator — PROJ](https://proj.org/en/stable/operations/projections/tmerc.html),
[SiteLocation — Autodesk](https://help.autodesk.com/cloudhelp/2026/ENU/Revit-API-MainReference/files/html/9d71159d-514c-c1b3-8673-5c0e7f28b688.htm)
e [BasePoint.Clipped — Autodesk](https://help.autodesk.com/cloudhelp/2026/ENU/Revit-API-MainReference/files/html/e93c4d28-5bbc-9619-8313-fba01852a8bc.htm).

Versão 0.8.3: ensaio no Revit 2026.5 com os 74 contornos selecionados no DWG real, georreferenciados por correspondência de 100% dos vértices do CSV ao layer CurvasTG. Os pisos foram criados e conferidos em documento temporário, incluindo cotas superiores e escavação; todas as alterações do ensaio foram revertidas. O projeto aberto foi apenas consultado. Pisos criados em versões anteriores precisam ser gerados novamente com a nova referência.
