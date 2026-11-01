# Greenlight: primeira etapa de integracao com Cartorio Digital Bitcoin

**Estado:** integracao de **consulta autenticada de identidade**, sem faturas e sem mover BTC. No e carteira ainda NAO configurados pelo projeto. Mainnet continua com `allow_mainnet_invoices=false`.

## Por que este conector existe

Blockstream Greenlight hospeda o Core Lightning de um usuario; o `gl-client` conversa com o Scheduler para agendar o no, autentica com credenciais de dispositivo via mTLS, e consulta informacoes. O no pode ser desligado em periodos de inatividade. O signer precisa permanecer disponivel para assinaturas e operacoes financeiras, incluindo **criar invoice**.

O conector `cartorio_documentos/greenlight.py` usa as chamadas da [documentacao oficial](https://blockstream.github.io/greenlight/getting-started/schedule/):

```python
device_creds = Credentials.from_bytes(arquivo_privado)
scheduler = Scheduler("bitcoin", device_creds)
node = scheduler.node()
info = node.get_info()
```

Ele confere a identidade publica do no e a rede antes de retornar sucesso. **Nao acessa signer, seed, invoices, pagamentos, canais ou saldo.** Todos os comandos financeiros sao bloqueados pelo conector. Os testes usam um SDK simulado, sem acessar a rede Bitcoin. A SDK opcional Python esta fixada em `gl-client==0.3.4`.

## Primeira conexao (pelo operador, sem enviar segredos por chat)

1. Use o [Greenlight Developer Console](https://greenlight.blockstream.com/) e siga o procedimento oficial para criar/recuperar o no. O servico pode exigir cadastro, convite ou certificado de desenvolvedor conforme sua conta. Guarde seed e identidade do dispositivo apenas em meio confiavel. Nunca envie chave privada, seed, certificados ou arquivo de credenciais ao GitHub/ChatGPT.
2. No Linux do operador, depois de clonar este repositorio, instale Python 3.12 numa venv e:
   ```bash
   python -m pip install -r requirements-documentos.txt
   python -m pip install -r requirements-greenlight.txt
   ```
3. Coloque o **arquivo de credenciais de dispositivo** emitido pelo Greenlight fora do repositorio, por exemplo em `/etc/cartorio/greenlight-device.gfs`. Permissoes de arquivo: `0600` ou `0400`, dono o usuario da aplicacao. Nao copie a seed do signer para o servidor.
4. Pegue a chave publica `node_id` da sua conta Greenlight, com 66 caracteres hexadecimais (iniciando em `02` ou `03`), e consulte:
   ```bash
   python -m cartorio_documentos greenlight-status \
       --device-credentials-file /etc/cartorio/greenlight-device.gfs \
       --expected-node-id CHAVE_PUBLICA_DO_SEU_NO \
       --greenlight-network bitcoin
   ```
5. A saida de sucesso confirma apenas conexao e identidade; **nao habilita recebimento**. Se houver erro, confira SDK, permissao do arquivo, registro, credenciais e disponibilidade do Greenlight.

## Dependencias para receber tarifas Lightning

- Assinador das chaves (`Signer`) em **dispositivo de controle do usuario**, sempre com backup seguro, que acompanhe o agendamento do Greenlight. [Documento](https://blockstream.github.io/greenlight/getting-started/schedule/).
- Implementar no Cartorio um segundo adaptador que use os metodos gRPC de **invoice / list-invoices**, valida tipos protobuf da versao adotada, idempotencia e reconciliacao das faturas sem poder pagar/retirar/abrir canais; revisar autorizacao/autenticacao de device creds (eles podem ser poderosos), separar credenciais financeiras e de diagnostico.
- Garantir capacidade real de recebimento nos canais e reserva de fundo para as taxas de abertura/liquidez, sem assumir receita de roteamento. Confirmar custos, termos e limite gratuito vigentes.
- Implementar regra de ativacao, testes em testnet e um teste supervisionado de valor pequeno em mainnet, com `allow_mainnet_invoices=false` ate conclusao.
- Para registrar na blockchain, as provas OpenTimestamps ainda devem ser verificadas com Bitcoin Core sincronizado/uma fonte independente confiavel. Greenlight nao fornece Bitcoin Core completo controlado pelo cartorio.
- O Greenlight nao garante uptime 24h de nos gratuitos: pode parar no de inatividade. O proprio dispositivo do signer deve estar disponivel para assinar.

## Verificacoes feitas

- Testes automatizados cobrem SDK mockado, identidade, rede, credenciais privadas, erros redigidos e recusa de operacoes financeiras.
- Integracao real ao servico **aguarda credenciais de dispositivo da conta do operador**, obtidas fora desta conversa.
- Nenhum fundo, carteira, seed ou canal foi criado ou movimentado por esta entrega.

Fontes oficiais:
- https://blockstream.github.io/greenlight/getting-started/
- https://blockstream.github.io/greenlight/getting-started/installation/
- https://blockstream.github.io/greenlight/getting-started/register/
- https://blockstream.github.io/greenlight/getting-started/schedule/
- https://blockstream.github.io/greenlight/reference/creds/
