# Mineracao 24/7 nao equivale a hospedagem de Bitcoin Core e Lightning

**Decisao (01/11/2026): nao implantar carteiras ou canais do cartorio em infraestrutura de mineracao sem acesso explicito a um servidor Linux persistente.**

Um pool de mineracao disponibiliza endpoints Stratum e contabiliza shares/hashrate, mas isso **nao** implica SSH, root, espaco em disco, backups ou uma instancia Linux executando software do cliente. Alugar hashrate nao significa alugar uma VPS. Miners ASIC sao maquinas especializadas e normalmente nao substituem o computador que executa Bitcoin Core/CLN.
- Braiins Pool: https://academy.braiins.com/braiins-pool/btc-mining-setup
- Braiins Hashpower: https://braiins.com/blog/buy-bitcoin-hashrate-introducing-braiins-hashpower
- Funcao dos nos na mineracao: https://help.blockstream.com/education/nodes/introduction-and-role/what-is-the-role-of-a-node-in-mining

## Servicos de nos Bitcoin/Lightning sao mais pertinentes

| Opcao | Tipo | Bitcoin Core independente do cartorio? | Lightning | Custo/disponibilidade |
|---|---|---|---|---|
| Pool ou aluguel de mineracao (Braiins) | Hasing/Stratum | Nao | Nao garante | Nao entrega VPS do assinante |
| Blockstream **Greenlight** | Core Lightning remoto gerenciado | Nao | Sim, em modalidade nao custodial com chaves do usuario | Oferece acesso de desenvolvimento gratuito com nos sob demanda; uptime continuo nao garantido no plano gratuito |
| Nodana | Hospedagem de nos Phoenixd | Nao | Sim, mediante plano e cobranca por uso | Sem cartao, mas **US$ 12/no/mes** de referencia, cobrado proporcionalmente; custo nao zero |
| VPS Linux comunitaria sem cartao | Acesso administrativo conforme plano | Potencialmente, se RAM/disco/rede bastarem | Potencialmente | Renovacoes, recuperacao/suspensao, backups sem garantia |
| PC Linux proprio | Hardware e disco do operador | Sim | Sim | Sem mensalidade de cloud; tem custo de energia/conexao, backups e manutencao |

Fontes:
- https://blockstream.github.io/greenlight/
- https://github.com/Blockstream/greenlight
- https://blockstream.com/press-releases/2023-10-12-blockstream-greenlight-scalable-lightning-integration/
- https://nodana.io/pricing
- https://docs.corelightning.org/docs/bitcoin-core

## Por que nao basta apontar a configuracao do cartorio para Greenlight

O modulo atual (`cartorio_documentos/lightning.py`) espera **CLNRest HTTPS com TLS + Rune**, com chamadas como `/v1/invoice`, `/v1/listinvoices` e `/v1/getinfo`. O **Greenlight usa scheduler/node via gRPC com autenticacao e key manager**, incluindo protocolos de assinatura; nao e a mesma API. Substituir `lightning_rest_url` por um endereco Greenlight **nao funciona**.

Para suportar Greenlight seria necessario implementar um adaptador separado no modulo de cobranca que:
1. Identifique de forma verificavel o proprio no (mainnet) registrado no servico e valide sua identidade.
2. Gerencie conexoes gRPC autenticadas e mantenha a parte de assinatura/chaves sob o controle do operador. Nenhuma seed ou certificado secreto no front-end ou no GitHub.
3. Crie e consulte faturas por identificadores exclusivos; concilie `payment_hash`, montante, estado e comprovacoes, inclusive expiracoes/duplicatas.
4. Mantenha fila persistente de reconciliacao e tratamento de indisponibilidade. Nunca marque pagamento como confirmado por webhook nao autenticado ou mero envio de pedido.
5. Tenha testes unitarios com respostas falsas e um teste real pequeno **autorizado** na mainnet, verificando custos e liquidez.
6. Distinga operacionalmente comprovacao OTS de blocos Bitcoin (continua exigindo verificacao independente ou fonte externa explicitamente confiada) e recebimento por Lightning hospedado.
7. Preveja retirada/migracao dos fundos para outro operador em caso de encerramento do provedor, com backup da chave e canais conforme o processo suportado.

**Nao esta integrado:** este documento nao modifica a carteira ou instala Greenlight. O perfil CLNRest existente continua intocado e novas faturas mainnet ficam desligadas por padrao.

## Pre-requisitos para qualificar uma hipotetica mineradora que ofereca VPS

- Contrato explicito autoriza instalar Bitcoin Core e Lightning e hospedar carteira propria? 
- SSH/root em sistema Linux permanente, em vez de painel Stratum/mineracao?
- Disco persistente suficiente para IBD completa (ainda que podado), escrita SQLite, snapshots e cache?
- CPU/memoria adequadas e cotas sem suspensao por inatividade/mineracao?
- Regras de rede TCP (P2P), politica de portas e acesso por Tor?
- Snapshot e **copia externa independente** (incluindo procedimento de recuperacao adequado a canais)?
- Controle de segredos pelo titular, politica de interrupcao e exclusao de instancias?
- Custo e credito real, inclusive taxas por minuto, por disco, renovacao e saldo minimo?

Se qualquer item essencial nao for verificavel, manter como ambiente de teste sem BTC real e nao alegar que o no esta 24/7.

## Proximo passo executavel sem dados financeiros

Ha um script seguro para Linux em `deploy/sem-cartao/preparar-servidor.sh`:
```bash
bash deploy/sem-cartao/preparar-servidor.sh --diagnostico
```
Este comando **nao instala, cobra, altera firewalls ou movimenta carteira**. A opcao `--preparar-base` instala apenas componentes basicos em uma maquina Linux do operador ja aprovada.

**Status no GitHub:** arquivos de configuracao versionados, sem servidor de mineracao cedido ao projeto, nenhum acesso remoto, sem node mainnet operativo ou bitcoins reais recebidos.
