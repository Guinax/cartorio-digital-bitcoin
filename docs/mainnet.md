# Estrutura para Bitcoin mainnet

O perfil de producao acrescenta chave Ed25519 criptografada, CLNRest com TLS
verificado e Rune restrita, diagnostico de prontidao, backup autenticado,
restauracao em diretorio novo e um worker com fila persistente. A interface
continua sendo local para o operador. Esta entrega nao publica uma API ou
site, nao financia canais e nao transfere BTC.

O laboratorio continua separado. Passar nos testes comprova o comportamento
testado; ativacao comercial exige validar o servidor, seus nos e a operacao
na rede principal. O servico registra existencia e integridade de documentos;
as regras do Bitcoin continuam decidindo a validade das transferencias.

## Componentes e limites

| Componente | Responsabilidade |
| --- | --- |
| Bitcoin Core mainnet sincronizado | Validar a cadeia e fornecer cabecalhos para conferir provas |
| Core Lightning mainnet | Receber tarifas e, conforme seus canais, encaminhar pagamentos |
| CLNRest HTTPS + Rune restrita | Permitir ao modulo apenas criar faturas e consultar dados necessarios |
| Banco e chave do emissor | Guardar registros e assinar comprovantes |
| Worker | Reconciliar faturas, enviar compromissos, atualizar provas, verificar e revalidar |
| Backup do modulo | Preservar banco de documentos, provas e chave do emissor |

O modulo nao precisa da seed ou do `hsm_secret` do Lightning. Nao os envie
ao ChatGPT, nao os coloque na configuracao e nao os grave no repositorio.
O backup do modulo **nao e backup da carteira ou dos canais Lightning**.
Planeje separadamente a recuperacao de `hsm_secret`, `emergency.recover` e
estado dos canais segundo a documentacao oficial do Core Lightning. Restaurar
uma copia antiga de banco Lightning como se fosse atual pode colocar fundos
em risco; os comandos `backup` e `restore` deste projeto nao fazem isso.

## Preparar o servidor

Use Linux com disco persistente, relogio sincronizado e espaco dimensionado
para os nos. Instale Bitcoin Core e Core Lightning por fontes oficiais,
verificando as versoes e assinaturas dos binarios. Os modelos em
`deploy/mainnet/bitcoin.conf.example` e `lightning.config.example` precisam
ser adaptados ao servidor. Eles nao sao executados automaticamente.

- Mantenha Bitcoin RPC em loopback; o modelo de Bitcoin Core nao tem carteira.
- Mantenha CLNRest em loopback ou rede privada, com certificado verificavel.
- Nao publique RPC, CLNRest, banco ou arquivos de credenciais na internet.
- O usuario do aplicativo deve ter acesso somente ao cookie do Bitcoin Core,
  a Rune restrita e os dados do modulo; nao ao socket RPC ou seed do CLN.
- O cookie da RPC tem privilegios de RPC no servidor Bitcoin. A lista de
  metodos de leitura do modulo nao substitui isolamento do sistema operacional.
- Nao reutilize diretorios, credenciais ou carteiras do regtest em mainnet.

Instale o codigo em `/opt/cartorio` e crie uma venv usando
`requirements-documentos.txt`. Crie o usuario de sistema `cartorio` e os
diretorios `/etc/cartorio`, `/srv/cartorio/data` e `/srv/cartorio-backups`,
pertencentes a esse usuario, com modo `0700`. O software em `/opt/cartorio`
deve ser legivel, mas nao editavel pelo usuario do worker.

Gere uma senha aleatoria de pelo menos 32 bytes para a chave do emissor e
salve em `/etc/cartorio/issuer-password`, modo `0600`, sem imprimi-la em logs.
Gere a chave de backup, com o usuario `cartorio`:

```bash
/opt/cartorio/.venv/bin/python -m cartorio_documentos create-backup-key --out /etc/cartorio/backup.key
```

O comando recusa sobrescrever um arquivo existente. Guarde uma copia segura
e separada da senha e da chave de backup fora do servidor. Perde-las pode
impedir restauracao ou abertura da chave do emissor. A copia externa dos
backups nao e automatizada por esta versao; use uma rotina do servidor para
envia-los a armazenamento separado. Nao exclua versoes antigas antes de testar
a recuperacao e definir uma politica de retencao.

## Rune e certificado do Lightning

No usuario operador do **no Lightning**, crie uma Rune com estas restricoes:

```json
[
  ["method=getinfo", "method=invoice", "method=listinvoices", "method=listforwards", "method=listpeerchannels"],
  ["method/invoice", "pnamelabel^cartorio-documento-"],
  ["method/listinvoices", "pnamelabel^cartorio-documento-"]
]
```

Use `lightning-cli --network=bitcoin -k createrune restrictions=...` com o
JSON acima como um unico argumento. O valor do campo `rune` retornado deve
ficar em `/etc/cartorio/receiver.rune`, modo `0600`, acessivel ao usuario
`cartorio`. Nao use uma Rune irrestrita ou o socket da carteira no aplicativo.
A primeira regra permite apenas os cinco metodos. As outras limitam a
criacao e a consulta de faturas aos identificadores do servico. O cliente
tambem recusa comandos como `pay`, `withdraw`, `fundchannel` e `close`.

Copie o certificado/CA publico do CLNRest para `/etc/cartorio/cln-ca.pem`.
O hostname usado na URL precisa constar no certificado. O cliente nao tem
opcao para ignorar a verificacao TLS, recusa redirecionamentos e nao envia
credenciais por proxies do ambiente.

## Configurar e inicializar

Copie `deploy/mainnet/config.example.json` para `/etc/cartorio/config.json`.
Informe os caminhos reais e substitua `lightning_node_id` pelo `id` retornado
por `getinfo` no seu no. O exemplo e deliberadamente invalido sem essa
identidade real. A tarifa padrao continua **zero**; o limite de fatura e um
limite operacional configuravel, nao uma definicao de preco comercial.

Mantenha `allow_mainnet_invoices` como `false` durante a preparacao. Como
usuario `cartorio`, usando a venv do projeto:

```bash
python -m cartorio_documentos --config /etc/cartorio/config.json init
python -m cartorio_documentos --config /etc/cartorio/config.json backup
python -m cartorio_documentos --config /etc/cartorio/config.json work --once
python -m cartorio_documentos --config /etc/cartorio/config.json doctor
```

`init` cria uma identidade criptografada; nunca substitui chave existente.
Para proteger um banco antigo do **modulo de documentos**, preserve antes
uma copia protegida e execute, com o perfil de producao ainda desligado:

```bash
python -m cartorio_documentos --data /caminho/dados-documentos --key-password-file /etc/cartorio/issuer-password protect-key
```

Isso criptografa a mesma chave e preserva seus comprovantes. Um banco de
regtest nao e um banco mainnet. O diagnostico recusa registros misturados;
crie um diretorio de producao separado, preservando o laboratorio.

`doctor` nao abre canais, nao paga faturas e nao altera a tarifa. Ele verifica:

- permissoes privadas, chave criptografada e integridade do banco;
- backup recente, autenticado e vinculado ao emissor;
- sinal recente de atividade do worker e ausencia de falhas pendentes na fila;
- rede main, bloco genesis mainnet, sincronizacao e idade da ponta Bitcoin;
- identidade mainnet esperada do CLN, sincronizacao e capacidade estimada de
  recebimento em canais ativos e conectados.

O codigo de saida e `0` para diagnostico aprovado e `2` para diagnostico
incompleto. `ready_for_receiving` nao liga o interruptor de cobranca. O campo
`mainnet_invoices_enabled` informa separadamente se a emissao foi habilitada.
O diagnostico nao certifica a recuperabilidade dos canais, a politica real
da Rune ou a seguranca de todo o servidor. Liquidez e disponibilidade mudam.

## Processamento continuo e monitoramento

Adapte `deploy/mainnet/cartorio-worker.service`, instale a unidade no systemd
e habilite-a somente no servidor ja configurado. Ela executa com usuario
dedicado, sem privilegios adicionais e com escrita limitada aos dados e backups.

```bash
systemctl enable --now cartorio-worker
journalctl -u cartorio-worker
```

A fila SQLite guarda proxima tentativa, contador de falhas e resultado de
cada registro. Ha um limite de registros por ciclo, tentativas com intervalo
crescente e trava contra workers simultaneos. Registros confirmados sao
revalidados; uma nova verificacao falha retira o estado positivo anterior.
O worker trata somente registros mainnet, nunca gera ou paga faturas e nao
abre canais. O interruptor de novas faturas nao impede reconciliar pagamentos
ja recebidos. O status fica em `worker-status.json` e nos logs do servico.

Configure o monitor do servidor para executar `doctor` periodicamente e avisar
o operador se o codigo for diferente de zero, se o servico parar, se o disco
encher ou se os backups externos deixarem de chegar. Nenhum alerta por e-mail
ou mensagem e enviado automaticamente por este projeto.

O snapshot usa a API de backup SQLite e criptografia autenticada Fernet.
Esta primeira implementacao suporta banco de ate 64 MiB e arquivo de backup
de ate 128 MiB. Acima disso, o backup falha explicitamente e bloqueia novas
faturas quando o backup valido ficar antigo; planeje migracao antes do limite.
Nao ha remocao automatica de backups nesta versao. Dimensione espaco e retencao.

## Ensaiar recuperacao e liberar recebimento

Anote o fingerprint publico do emissor fornecido por `init`. Teste uma
restauracao em outro diretorio, antes de aceitar pagamentos de clientes:

```bash
python -m cartorio_documentos --config /etc/cartorio/config.json restore /caminho/arquivo.backup --destination /srv/cartorio/restore-test --issuer-fingerprint FINGERPRINT_DO_EMISSOR
```

O comando verifica criptografia, senha, identidade, hash e integridade SQLite
e recusa destinos existentes. Ele restaura apenas o modulo de documentos,
sem tocar no no Lightning. Verifique um comprovante antigo com o arquivo
original. O ensaio local nao substitui testar tambem a copia do backup externo.

Depois de configurar o servidor e seus backups, estabeleca a tarifa e um
limite por fatura apropriados. Com o diagnostico aprovado, a emissao pode ser
habilitada por `allow_mainnet_invoices: true`. Cada **nova** fatura consulta
novamente o diagnostico, o valor maximo e a capacidade de recebimento.
Faturas existentes continuam consultaveis com a emissao pausada.

A validacao final na rede principal deve incluir um documento sintetico,
uma fatura de valor previamente definido pelo operador, recebimento no no
esperado, comprovante correto e prova OTS confirmada com pelo menos seis
confirmacoes. Esta entrega nao executou esse pagamento nem financia a liquidez
necessaria. Faturas expiradas continuam preservadas, e a versao atual nao
as substitui automaticamente; isso evita criar cobrancas concorrentes.

## Validacao desta entrega

Em 01/11/2026, os [testes desta versao foram aprovados](https://github.com/Guinax/cartorio-digital-bitcoin/actions/runs/41326390942):
42 testes de assinatura, chave protegida, backup/restauracao, fila persistente,
diagnostico e HTTPS local, seguidos da integracao completa de documentos e
pagamento A -> B -> C com os nos executando em regtest. O teste confirmou
recebimento ficticio e nova taxa de 1.250 msat em B. Nenhum BTC real foi movido.
A verificacao de documento e o recebimento em mainnet continuam pendentes da
instalacao e validacao no servidor de producao.

Referencias oficiais: [Bitcoin Core](https://bitcoincore.org/),
[CLNRest](https://docs.corelightning.org/docs/rest),
[Runes](https://docs.corelightning.org/reference/createrune),
[backup de canais e carteira](https://docs.corelightning.org/docs/backup),
[OpenTimestamps](https://opentimestamps.org/).
