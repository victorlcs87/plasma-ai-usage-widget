# Medidor Percentual Semanal e Criacao de Contas via Interface Grafica

Contexto: A exibicao de capacidade bruta em quantidade de mensagens gerava ambiguidade para o usuario e a configuracao manual de novas contas via edicao direta de arquivo JSON em disco era propensa a erros de sintaxe e inviavel para uso cotidiano no desktop.
Decisao: Substituir a exibicao de contadores brutos de capacidade por dois medidores percentuais simetricos em cada card (Janela Ativa/Horaria e Janela Semanal), ambos com barra de progresso, percentual de uso e tempo de liberacao. Alem disso, expor o comando CLI `ai-usage-collector --add-account` e implementar um formulario grafico completo em `configGeneral.qml` para adicao de contas diretamente pelo KDE Plasma.
Motivo: Tornar a visualizacao de consumo mais intuitiva e coerente entre janelas temporais, e permitir o gerenciamento completo do ciclo de vida das contas (adicao e remocao) sem necessidade de abrir terminais ou editores de texto.
