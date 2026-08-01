/* ==========================================================================
   SGE - Interacoes da tela de chamada.

   Carregado apenas nesta pagina. Responsavel por:
     - marcar todos os alunos de uma vez;
     - exibir o campo de justificativa somente quando a situacao exige;
     - destacar visualmente a linha conforme a situacao;
     - manter os contadores de presentes e faltas atualizados.

   Todo o comportamento e progressivo: sem JavaScript a chamada continua
   funcionando, pois os botoes sao <input type="radio"> reais dentro de um
   <form> comum.
   ========================================================================== */

(() => {
  'use strict';

  const form = document.getElementById('formChamada');
  if (!form) return;

  const linhas = Array.from(document.querySelectorAll('[data-linha-chamada]'));

  /** Aplica a cor de fundo da linha conforme a situacao escolhida. */
  function estilizarLinha(linha, situacao) {
    linha.classList.remove('falta', 'justificada');
    if (situacao === 'falta') {
      linha.classList.add('falta');
    } else if (situacao === 'falta_justificada') {
      linha.classList.add('justificada');
    }
  }

  /** Mostra o campo de justificativa apenas para falta justificada. */
  function alternarJustificativa(matriculaId, situacao) {
    const campo = document.querySelector(`[data-justificativa-de="${matriculaId}"]`);
    if (!campo) return;
    campo.classList.toggle('d-none', situacao !== 'falta_justificada');
  }

  /** Recalcula os contadores exibidos no topo. */
  function atualizarContadores() {
    const marcados = form.querySelectorAll('input[type="radio"]:checked');
    let presentes = 0;
    let faltas = 0;

    marcados.forEach((radio) => {
      // Atraso e falta justificada contam como presenca para a frequencia
      // legal, mesma regra aplicada no servidor (SituacaoPresenca).
      if (radio.value === 'falta') faltas += 1;
      else presentes += 1;
    });

    const alvoPresente = document.querySelector('[data-contador="presente"]');
    const alvoFalta = document.querySelector('[data-contador="falta"]');
    if (alvoPresente) alvoPresente.textContent = presentes;
    if (alvoFalta) alvoFalta.textContent = faltas;
  }

  /** Extrai o id da matricula a partir do atributo name do radio. */
  function idDaMatricula(radio) {
    return radio.name.replace('situacao_', '');
  }

  /* --- Reacao a mudanca individual --- */
  form.addEventListener('change', (evento) => {
    const radio = evento.target;
    if (radio.type !== 'radio' || !radio.name.startsWith('situacao_')) return;

    const linha = radio.closest('[data-linha-chamada]');
    if (linha) estilizarLinha(linha, radio.value);

    alternarJustificativa(idDaMatricula(radio), radio.value);
    atualizarContadores();
  });

  /* --- Marcar todos --- */
  document.querySelectorAll('[data-marcar-todos]').forEach((botao) => {
    botao.addEventListener('click', () => {
      const alvo = botao.dataset.marcarTodos;

      linhas.forEach((linha) => {
        const radio = linha.querySelector(`input[data-situacao="${alvo}"]`);
        if (!radio || radio.disabled) return;

        radio.checked = true;
        estilizarLinha(linha, alvo);
        alternarJustificativa(idDaMatricula(radio), alvo);
      });

      atualizarContadores();
    });
  });

  /* --- Estado inicial --- */
  linhas.forEach((linha) => {
    const marcado = linha.querySelector('input[type="radio"]:checked');
    if (marcado) estilizarLinha(linha, marcado.value);
  });
  atualizarContadores();
})();
