/* ==========================================================================
   SGE - Interacoes da grade de lancamento de notas.

   Responsavel por:
     - navegacao vertical pelo teclado (Enter e setas), como em planilha;
     - realce visual de notas abaixo da media;
     - validacao imediata do intervalo permitido;
     - desativar o campo de nota quando o aluno e marcado como ausente.

   A validacao definitiva continua no servidor (`nota_service.salvar_notas`);
   aqui o objetivo e apenas dar retorno imediato a quem digita.
   ========================================================================== */

(() => {
  'use strict';

  const campos = Array.from(document.querySelectorAll('.sge-nota-input'));
  if (!campos.length) return;

  /** Media de aprovacao usada apenas para o realce visual. */
  const MEDIA_REFERENCIA = 6;

  /** Converte o texto digitado em numero, aceitando virgula decimal. */
  function paraNumero(texto) {
    const limpo = String(texto || '').trim().replace(',', '.');
    if (!limpo) return null;
    const numero = Number(limpo);
    return Number.isFinite(numero) ? numero : null;
  }

  /** Colore o campo conforme o desempenho e sinaliza valores invalidos. */
  function avaliarCampo(campo) {
    const valor = paraNumero(campo.value);
    const maximo = Number(campo.dataset.notaMaxima || 10);

    campo.classList.remove('abaixo-media', 'acima-media', 'is-invalid');

    if (valor === null) return;

    if (valor < 0 || valor > maximo) {
      campo.classList.add('is-invalid');
      campo.setAttribute('title', `A nota deve estar entre 0 e ${maximo}.`);
      return;
    }

    campo.removeAttribute('title');

    // Normaliza para a escala 0-10 antes de comparar com a media.
    const normalizada = maximo ? (valor / maximo) * 10 : valor;
    campo.classList.add(
      normalizada >= MEDIA_REFERENCIA ? 'acima-media' : 'abaixo-media',
    );
  }

  /** Move o foco para o campo de nota do proximo (ou anterior) aluno. */
  function moverFoco(campoAtual, direcao) {
    // Considera apenas os campos da aba visivel: cada avaliacao e uma aba.
    const visiveis = campos.filter((c) => c.offsetParent !== null);
    const indice = visiveis.indexOf(campoAtual);
    if (indice === -1) return;

    const proximo = visiveis[indice + direcao];
    if (proximo) {
      proximo.focus();
      proximo.select();
    }
  }

  campos.forEach((campo) => {
    avaliarCampo(campo);

    campo.addEventListener('input', () => avaliarCampo(campo));
    campo.addEventListener('focus', () => campo.select());

    campo.addEventListener('keydown', (evento) => {
      if (evento.key === 'Enter' || evento.key === 'ArrowDown') {
        evento.preventDefault();
        moverFoco(campo, 1);
      } else if (evento.key === 'ArrowUp') {
        evento.preventDefault();
        moverFoco(campo, -1);
      }
    });
  });

  /* --- Ausencia desativa o campo de nota --- */
  document.querySelectorAll('input[name^="ausente_"]').forEach((caixa) => {
    const linha = caixa.closest('tr');
    const campoNota = linha ? linha.querySelector('.sge-nota-input') : null;
    if (!campoNota) return;

    const sincronizar = () => {
      campoNota.disabled = caixa.checked;
      if (caixa.checked) {
        campoNota.value = '';
        campoNota.classList.remove('abaixo-media', 'acima-media', 'is-invalid');
      }
    };

    caixa.addEventListener('change', sincronizar);
    sincronizar();
  });
})();
