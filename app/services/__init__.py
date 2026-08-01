"""Camada de servicos: onde vivem as regras de negocio do SGE.

Contrato desta camada
---------------------
1. Services **nao** conhecem ``request``, ``session`` nem ``flash``. Eles
   recebem dados ja validados e devolvem objetos ou lancam excecoes de
   dominio (``app/services/excecoes.py``).
2. Consequencia pratica: a mesma regra atende a interface web, os comandos
   CLI, os testes e — sem reescrita — a futura API JSON consumida por um
   aplicativo Android.
3. Services controlam a transacao (``commit``/``rollback``). As rotas apenas
   traduzem o resultado para a tela.
"""
