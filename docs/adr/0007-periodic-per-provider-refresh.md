# ADR 0007: Atualizacao Periodica por Provedor

Status: accepted (substitui ADR-0003)

O modelo estritamente sob demanda da ADR-0003 impede notificacoes de limite, Previsao de Esgotamento, Ritmo de Uso e contagem regressiva confiavel, que dependem de dados recentes sem acao do usuario. Decidimos que o Plasmoid aciona o coletor em um Intervalo de Atualizacao proprio de cada provedor (padrao de 5 minutos, minimo de 60 segundos). O coletor respeita `retry-after` e aplica backoff exponencial apos HTTP 429, serve o ultimo resultado em cache durante as pausas e marca os dados como desatualizados para que a interface os esmaeca. "Atualizar agora" continua disponivel.

## Considered Options

- Manter sob demanda: rejeitado porque inviabiliza as funcoes de alerta e previsao pedidas pelo usuario.
- Daemon/servico systemd do coletor: rejeitado; o temporizador no Plasmoid basta e nao exige instalar servicos.
