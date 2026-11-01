# Cartório Digital Bitcoin

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
- Imagens e script tiveram revisão estática, mas o laboratório **ainda precisa ser executado no Codespaces**. A conclusão só é comprovada quando o script exibir SUCESSO e taxas positivas.
- Para operar um nó Lightning real, seria necessário capital em BTC, canais financiados, liquidez, backups seguros, monitoramento, disponibilidade e estudo dos custos e riscos. Não existe receita garantida por apenas manter um nó ligado.

Documentação: [Core Lightning](https://docs.corelightning.org/docs/beginners-guide) · [Configuração](https://docs.corelightning.org/docs/configuration) · [Taxas de canal](https://docs.corelightning.org/reference/setchannel).
