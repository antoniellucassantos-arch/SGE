"""Utilitarios transversais do SGE.

Reune helpers usados por mais de uma camada: seguranca, validacao,
autorizacao, formatacao para apresentacao, manipulacao de arquivos e
paginacao.

Fronteira com ``services/``
---------------------------
A regra, em uma linha: **``services/`` conhece o banco; ``utils/`` e funcao
pura.** Um modulo daqui nao consulta tabela, nao abre transacao e nao chama
service. Se um arquivo de ``utils/`` precisar importar um model para
consultar dados, ele e um service disfarcado e deve mudar de pasta.

Duas excecoes, ambas deliberadas:

* ``app.models.enums`` — enumeracoes sao vocabulario do dominio, nao acesso
  a dados. ``permissoes.py`` precisa de ``PapelUsuario`` para existir.
* ``app.services.excecoes`` — classes de excecao, sem comportamento e sem
  banco. Levantar ``ErroArquivo`` de ``arquivos.py`` e o caminho certo.

``decoradores.py`` e o unico modulo que consulta o banco, e por um motivo
claro: a camada 2 da autorizacao *precisa* olhar o registro para decidir se
aquele professor leciona naquela turma. As consultas ficam dentro das
funcoes, importadas na hora do uso, para nao criar ciclo de import.

Nenhum modulo daqui importa blueprints, o que mantem o grafo de dependencias
aciclico.
"""
