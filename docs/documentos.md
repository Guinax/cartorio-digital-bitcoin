# Modulo de registro de documentos

Implementacao local para Python 3.10 ou superior. O laboratorio Lightning
continua com sua configuracao e volumes existentes. Este modulo nao inicia
nos publicos, abre canais, paga faturas, movimenta BTC nem publica um site.

## O que o comprovante significa

| Evidencia | O que pode ser conferido |
| --- | --- |
| SHA-256 + tamanho | Se o arquivo apresentado corresponde exatamente ao registrado |
| Assinatura Ed25519 | Se o comprovante foi assinado pelo emissor cuja chave publica o verificador confia |
| Prova OpenTimestamps completa + Bitcoin Core | Existencia do compromisso do arquivo ate o horario do bloco Bitcoin correspondente |
| Fatura Lightning liquidada | Recebimento da tarifa pelo no configurado, com valor, rede e preimagem conferidos |

Essas evidencias nao atestam autoria, identidade civil, verdade do conteudo ou
autorizacao para transferir bitcoins. O nome do projeto nao lhe concede fe
publica nem o transforma em cartorio oficial. O horario `registered_at_server`
e o relogio local; `block_time` e o horario do bloco, nao a hora exata da criacao
do documento. A chave de assinatura e do servico, nao do autor do documento.

## Instalacao no Codespaces

Na raiz do repositorio:

```bash
git pull --ff-only
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements-documentos.txt
python3 -m cartorio_documentos init
```

`init` cria `.cartorio-documentos/registry.sqlite3`, uma chave privada local
`issuer-private.pem` e a publica `issuer-public.pem`. Reexecutar nao troca a
chave. Guarde backup protegido do banco **e da chave privada**, fora do
Codespace. Nao publique a chave privada, cookies RPC ou banco em repositorios.
O Codespace pode ser suspenso ou apagado; para atendimento continuo sera
necessario um servidor persistente com backups e monitoramento.

## Registrar e verificar o arquivo

```bash
python3 -m cartorio_documentos register /caminho/contrato.pdf > .cartorio-documentos/comprovante.json
```

O JSON informa `payload.record_id`. Nos comandos seguintes, substitua `ID`
por esse identificador. Registrar novamente o mesmo arquivo devolve o mesmo
registro, sem duplicar uma cobranca.

```bash
python3 -m cartorio_documentos receipt ID
python3 -m cartorio_documentos verify-receipt /caminho/contrato.pdf --receipt .cartorio-documentos/comprovante.json --public-key .cartorio-documentos/issuer-public.pem
```

`verify-receipt` funciona sem rede. A chave publica deve ser obtida do emissor
por um canal confiavel; uma chave fornecida por um atacante junto com um
comprovante nao estabelece confianca. O resultado deste comando **nao**
confirma a blockchain. Arquivo alterado, chave diferente ou comprovante
adulterado encerram com codigo 1.

## Enviar a prova para o Bitcoin

```bash
python3 -m cartorio_documentos stamp ID
python3 -m cartorio_documentos upgrade ID
python3 -m cartorio_documentos export-proof ID --out .cartorio-documentos/contrato.pdf.ots
```

`stamp` envia um compromisso aleatorio derivado do hash aos calendarios
OpenTimestamps publicos. O arquivo original nao e enviado. Esses calendarios
agregam compromissos e os ancoram no Bitcoin; a confirmacao pode levar horas.
O sistema so grava prova se ao menos um calendario retornar uma atestacao.
Falhas preservam o registro e permitem nova tentativa. `upgrade` consulta
apenas os calendarios permitidos e pode ser executado novamente mais tarde.
Uma atestacao recebida de um calendario continua `pending` ate verificacao
contra o no Bitcoin.

O `.ots` pode ser verificado independentemente deste projeto com o documento
original e ferramentas OpenTimestamps. Para verificacao neste modulo, use um
**Bitcoin Core mainnet sincronizado**, independente do Bitcoin regtest do lab:

```bash
python3 -m cartorio_documentos verify-bitcoin ID --cookie /caminho/bitcoin/.cookie
python3 -m cartorio_documentos receipt ID > .cartorio-documentos/comprovante-atualizado.json
```

RPC local padrao: `http://127.0.0.1:8332`. RPC remoto exige HTTPS. A autenticacao
usa arquivo cookie local, nunca senha na linha de comando. A verificacao
confere SHA-256, caminho da prova ate a raiz Merkle, cabecalho e hash do bloco,
cadeia mainnet, sincronizacao, seis confirmacoes por padrao e uma nova leitura
do hash do bloco. O no RPC precisa ser confiavel e validar a cadeia por conta
propria. O modulo nao implementa consenso Bitcoin; usa Bitcoin Core para isso.

O resultado `verified_at_check` e uma fotografia da verificacao, com bloco,
horario, confirmacoes e instante da consulta. Uma nova verificacao falha
remove o estado positivo anterior. Revalidar a prova permite detectar mudancas
na cadeia; nao ha monitoramento automatico de reorganizacoes nesta versao.

## Tarifa pelo servico e cobranca Lightning

A tarifa inicial e **zero**; nenhum preco comercial foi definido. Para criar
um novo registro com tarifa, o operador pode configurar um valor inteiro em
millisatoshis; 1000 msat = 1 satoshi. O valor fica fixo naquele registro.

Exemplo **ficticio em regtest**, usando o laboratorio existente:

```bash
python3 -m cartorio_documentos --fee-msat 2500 register /caminho/outro-documento.pdf
python3 -m cartorio_documentos invoice ID --lab
```

No terminal do laboratorio, o operador pode pagar a fatura de teste pelo
no A, copiando o `bolt11` exibido pelo modulo:

```bash
docker compose -f laboratorio-lightning/compose.yaml exec -T lightning-a lightning-cli --network=regtest pay FATURA_BOLT11
python3 -m cartorio_documentos sync-payment ID --lab
python3 -m cartorio_documentos stamp ID
python3 -m cartorio_documentos forwards --lab
```

O comando `pay` acima e uma acao manual **exclusiva do laboratorio regtest**.
O modulo recebe a tarifa em C; a consulta `forwards --lab` observa as taxas
de roteamento em B. Sao receitas de naturezas diferentes. Mesmo quando a
tarifa e ficticia, `stamp` usa os calendarios publicos e cria uma prova real
de existencia do documento. Nao envie dados pessoais nos documentos de teste.

O laboratorio precisa ter terminado com `SUCESSO` antes desse exemplo. Se o
canal necessario nao estiver disponivel, o pagamento falha normalmente. Nao
apague volumes para corrigir. Faturas expiram em uma hora; esta versao nao
recria uma fatura expirada do mesmo registro. Preserve o registro e resolva
com o operador antes de realizar outra cobranca.

Para conectar um **no real ja preparado pelo operador**, configure o comando
local como lista JSON (sem shell) e a rede de cobranca explicitamente:

```bash
export CARTORIO_LIGHTNING_COMMAND='["lightning-cli", "--network=bitcoin", "--lightning-dir=/caminho/no-real"]'
python3 -m cartorio_documentos --network bitcoin --fee-msat VALOR_EM_MSAT register /caminho/documento.pdf
python3 -m cartorio_documentos --network bitcoin invoice ID
python3 -m cartorio_documentos --network bitcoin sync-payment ID
```

Esses comandos apenas conectam um no existente; nao configuram ou financiam
canais. Rede, identificador, valor esperado, valor recebido, hash de pagamento
e preimagem precisam conferir antes de marcar `paid`. Nao existe endpoint
para o cliente dizer que pagou. Sem confirmacao da tarifa, `stamp` e bloqueado.
O modulo nao possui comando para pagar, sacar ou abrir canais.

## Limite do modelo de pedagio

Um observador nao pode autorizar, reter ou taxar todas as transacoes Bitcoin.
A rede publica valida transferencias pelas suas proprias regras. Nosso
servico pode cobrar para registrar documentos de clientes que o contratam.
O proprio no Lightning pode receber taxas pelos pagamentos efetivamente
roteados pelos seus canais; os usuarios podem escolher outras rotas.

`forwards` consulta apenas encaminhamentos `settled` retidos pelo no. Nao
mostra todo o trafego da rede, nao soma falhas como renda e nao garante receita.
O modulo nao cria custodia, escrow ou coassinatura de transferencias.

## Limites operacionais e testes

Esta primeira versao fornece biblioteca Python e CLI **local do operador**.
Nao ha interface publica, contas de clientes, API multiusuario, envio remoto
de arquivos ou autenticacao de identidade. Nao exponha um terminal ou socket
RPC como se fosse uma API publica. Banco e provas sao locais e persistentes;
nao ha exportacao automatica de backup ou atualizacao automatica de provas.

```bash
python3 -m unittest discover -s tests -v
```

Os testes verificam assinaturas reais, alteracao de documentos/comprovantes,
serializacao OTS, bloqueio de calendario nao permitido, perda de chave,
pagamento, subpagamento, preimagem, redes e reorg. Calendarios, no Bitcoin
e no Lightning sao simulados nos testes; isso nao comprova uma operacao
financeira mainnet. Validacao de ponta a ponta exige os servicos correspondentes.

Para validar o recebimento com Bitcoin Core e tres nos Core Lightning em
execucao, sem mocks e usando exclusivamente regtest:

```bash
python3 laboratorio-lightning/teste_documentos.py --preparar
```

Sem `--preparar`, o teste usa o laboratorio ja iniciado. Ele usa um banco e
uma chave temporarios exclusivos, gera um documento sintetico, verifica
assinatura, exige pagamento, paga A -> B -> C, confirma a fatura em C e mede
somente novas taxas em B. Antes do pagamento, confere a rede de todos os nos.
Nao modifica o banco de documentos do operador nem apaga volumes do Docker.
Nao envia compromissos a calendarios publicos e nao afirma confirmar mainnet.

O workflow `.github/workflows/documentos.yml` executa os testes locais e essa
integracao em um servidor temporario do GitHub. O resumo publicado inclui
somente os resultados e valores ficticios, sem chaves privadas, preimagens ou
faturas. Pode ser repetido pela aba Actions, em `Run workflow`.

Referencias primarias:

- [OpenTimestamps](https://opentimestamps.org/)
- [Cliente oficial e verificacao independente](https://github.com/opentimestamps/opentimestamps-client)
- [Core Lightning: listinvoices](https://docs.corelightning.org/reference/listinvoices)
- [Core Lightning: listforwards](https://docs.corelightning.org/reference/listforwards)
- [Funcionamento do Bitcoin](https://bitcoin.org/en/how-it-works)
