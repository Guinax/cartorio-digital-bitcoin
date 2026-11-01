# Cartório Digital Bitcoin

## Registro de documentos

O projeto agora inclui o modulo real `cartorio_documentos`: SHA-256 do arquivo,
comprovante assinado com Ed25519, prova de existencia OpenTimestamps exportavel,
verificacao contra Bitcoin Core mainnet e cobranca opcional por Core Lightning.
O original permanece com o operador; apenas seu hash e metadados minimos ficam
no banco local. Os calendarios recebem um compromisso com nonce.

**Um registro local ou uma prova pendente ainda nao e confirmacao no Bitcoin.**
A confirmacao exige uma prova OTS completa e Bitcoin Core mainnet sincronizado.
Este servico registra integridade e existencia; nao comprova autoria, identidade
ou veracidade do documento e nao emite atos de um cartorio oficial.

Instalacao e comandos: [manual do modulo](docs/documentos.md).

Preparacao para a rede principal: [perfil mainnet, backups e operacao continua](docs/mainnet.md).
O perfil inclui chave criptografada, CLNRest HTTPS com acesso restrito,
diagnostico antes de novas faturas e worker para reconciliar pagamentos e
revalidar provas. Os modelos ficam em `deploy/mainnet/`; a emissao mainnet
vem pausada e depende da configuracao dos nos e do servidor.

### Testar documento e pagamento juntos

Depois de instalar as dependencias do modulo, execute na raiz do projeto:

```bash
python3 laboratorio-lightning/teste_documentos.py --preparar
```

Esse comando inicia ou retoma o laboratorio, registra um arquivo sintetico,
gera uma fatura, paga de A para C via B, confere o recebimento da tarifa e
mede somente as novas taxas de B. Tambem testa o bloqueio antes do pagamento
e a recusa de um arquivo alterado. Tudo ocorre em **regtest, sem BTC real**;
nao e uma confirmacao de documento no Bitcoin mainnet e nao envia dados
a calendarios publicos. Os volumes existentes sao preservados.

[Acompanhar os testes automaticos](https://github.com/Guinax/cartorio-digital-bitcoin/actions/workflows/documentos.yml).

O modulo nao controla a rede Bitcoin nem cobra por transacoes observadas.
A tarifa de registro remunera o nosso servico. Taxas de roteamento Lightning
ocorrem apenas nos pagamentos encaminhados com sucesso pelo proprio no.

## Laboratorio Lightning existente

Laboratório experimental de infraestrutura Lightning, totalmente **separado do Mundo Pet e da Mansão Maromba**.

## O que demonstra

Uma rede isolada **Bitcoin regtest** (bitcoins fictícios) com quatro contêineres Docker:

- Bitcoin Core: blockchain local de testes
- Nó **A**: realiza um pagamento Lightning
- Nó **B**: encaminha o pagamento e recebe uma taxa de roteamento fictícia
- Nó **C**: recebe o pagamento

O script `laboratorio-lightning/run_lab.py` prepara a blockchain, financia carteiras fictícias, abre canais A → B e B → C, configura uma taxa no nó B, executa o pagamento e consulta `listforwards`.

**Nenhum BTC real é necessário ou movimentado aqui. Isso não gera renda.**

## Executar pelo Android usando GitHub Codespaces

Abra um Codespace do repositório na branch `Master`. No terminal, a partir da raiz do projeto, execute:

```bash
git pull
python3 laboratorio-lightning/run_lab.py
```

Na primeira execução o Docker baixará imagens e construirá a imagem do Core Lightning. Pode demorar e usar recursos cobrados do Codespaces. Confira seu limite e encerre o Codespace quando terminar.

### Etapa 2: testar cinco pagamentos e medir novas taxas

Depois de executar o laboratorio e confirmar o primeiro pagamento, rode na raiz do projeto:

```bash
git pull && python3 laboratorio-lightning/teste_taxas.py
```

Esse teste em **regtest** envia cinco pagamentos ficticios de A para C, passando por B.
O resumo mostra quantos encaminhamentos foram liquidados, as **novas taxas**
de B em millisatoshis (msat) e o total acumulado. O valor anterior nao e
contado como ganho novo. O teste nao usa bitcoins reais e nao configura
uma operacao publica. Se algum pagamento falhar, o script mostra o erro;
nao remova volumes Docker para tentar corrigir sem antes diagnosticar.

### Consultar encaminhamentos e taxas em B

```bash
docker compose -f laboratorio-lightning/compose.yaml exec -T lightning-b lightning-cli --network=regtest listforwards settled
```

### Consultar contêineres

```bash
docker compose -f laboratorio-lightning/compose.yaml ps
```

### Se um contêiner Lightning ficar reiniciando

A configuração inicia `lightningd` diretamente em primeiro plano, com `init`
e rede `regtest` explícita. Isso evita depender do wrapper da imagem, que
calcula o diretório RPC usando `LIGHTNINGD_NETWORK=bitcoin` por padrão,
mesmo quando o comando seleciona regtest.

No Codespace existente, atualize os arquivos e execute novamente a preparação:

```bash
git pull --ff-only
python3 laboratorio-lightning/run_lab.py
```

O script recria os contêineres quando a configuração muda e mantém os volumes.
Execute `teste_taxas.py` somente depois que a preparação mostrar `SUCESSO`.
Se a falha continuar, consulte o estado e os logs antes de outra alteração:

```bash
docker compose -f laboratorio-lightning/compose.yaml ps -a
docker compose -f laboratorio-lightning/compose.yaml logs --tail=80
```

Não use `down -v` para corrigir reinícios: esse comando apaga os volumes.
A mudança de inicialização precisa ser validada executando o laboratório
no Docker; a revisão de configuração, sozinha, não comprova os pagamentos.

### Desligar os contêineres quando terminar

```bash
docker compose -f laboratorio-lightning/compose.yaml down
```

**Atenção:** `down` não interrompe a cobrança do Codespace enquanto ele continuar ligado. Encerre também o Codespace pela interface do GitHub.

## Segurança e limitações

- Ambiente **regtest**; não é mainnet nem Lightning pública.
- Portas dos contêineres não são publicadas para a internet. A rede Docker é interna.
- A senha RPC publicada no arquivo é **apenas para este regtest isolado**. Nunca reutilize em mainnet.
- Os volumes Docker persistem entre execuções. Para recomeçar do zero, é preciso remover os volumes deliberadamente, o que **apaga apenas os dados fictícios do laboratório**.
- O laboratorio e a integracao de documentos foram executados com sucesso no GitHub Actions em 01/11/2026: [resultado da execucao](https://github.com/Guinax/cartorio-digital-bitcoin/actions/runs/41324043597). A instalacao em cada Codespace ainda depende do estado daquele ambiente; confirme `SUCESSO` no terminal ao executar ali.
- Para operar um nó Lightning real, seria necessário capital em BTC, canais financiados, liquidez, backups seguros, monitoramento, disponibilidade e estudo dos custos e riscos. Não existe receita garantida por apenas manter um nó ligado.

Documentação: [Core Lightning](https://docs.corelightning.org/docs/beginners-guide) · [Configuração](https://docs.corelightning.org/docs/configuration) · [Taxas de canal](https://docs.corelightning.org/reference/setchannel).
