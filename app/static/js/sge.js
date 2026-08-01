/* ==========================================================================
   SGE - Sistema de Gestao Escolar
   JavaScript da interface (ES6, sem dependencias alem do Bootstrap).

   Organizado em modulos independentes inicializados por `iniciar()`. Cada
   modulo verifica a existencia dos seus elementos antes de agir, de modo que
   o mesmo arquivo serve todas as paginas sem erro de console.
   ========================================================================== */

(() => {
  'use strict';

  /* ------------------------------------------------------------------ */
  /* Utilitarios                                                        */
  /* ------------------------------------------------------------------ */
  const $ = (seletor, escopo = document) => escopo.querySelector(seletor);
  const $$ = (seletor, escopo = document) => Array.from(escopo.querySelectorAll(seletor));

  /** Token CSRF publicado no <head>; obrigatorio em toda requisicao de escrita. */
  const obterTokenCSRF = () => $('meta[name="csrf-token"]')?.content ?? '';

  /** Atraso de execucao: evita disparar busca a cada tecla digitada. */
  const debounce = (fn, espera = 300) => {
    let temporizador;
    return (...args) => {
      clearTimeout(temporizador);
      temporizador = setTimeout(() => fn(...args), espera);
    };
  };

  /** Remove acentos para permitir busca tolerante ("jose" acha "Jose"). */
  const semAcentos = (texto) =>
    (texto || '').normalize('NFD').replace(/\p{M}/gu, '').toLowerCase();

  const apenasDigitos = (valor) => (valor || '').replace(/\D/g, '');

  /* ==================================================================== */
  /* 1. Barra lateral                                                     */
  /* ==================================================================== */
  const BarraLateral = {
    CHAVE_RECOLHIDA: 'sge:lateral-recolhida',
    LARGURA_DESKTOP: 992,

    iniciar() {
      this.botao = $('#alternarLateral');
      this.sobreposicao = $('#sobreposicaoLateral');
      if (!this.botao) return;

      // Restaura a preferencia de menu recolhido (apenas no desktop).
      if (this.ehDesktop() && localStorage.getItem(this.CHAVE_RECOLHIDA) === '1') {
        document.body.classList.add('sge-lateral-recolhida');
      }

      this.botao.addEventListener('click', () => this.alternar());
      this.sobreposicao?.addEventListener('click', () => this.fechar());

      // Esc fecha a gaveta em telas pequenas.
      document.addEventListener('keydown', (evento) => {
        if (evento.key === 'Escape') this.fechar();
      });

      // Ao girar o aparelho ou redimensionar, normaliza o estado.
      window.addEventListener('resize', debounce(() => {
        if (this.ehDesktop()) this.fechar();
      }, 150));

      // Navegar em telas pequenas deve fechar a gaveta.
      $$('.sge-lateral__item').forEach((link) => {
        link.addEventListener('click', () => {
          if (!this.ehDesktop()) this.fechar();
        });
      });

      this.sincronizarSobreposicao();
    },

    ehDesktop() {
      return window.innerWidth >= this.LARGURA_DESKTOP;
    },

    alternar() {
      if (this.ehDesktop()) {
        const recolhida = document.body.classList.toggle('sge-lateral-recolhida');
        localStorage.setItem(this.CHAVE_RECOLHIDA, recolhida ? '1' : '0');
        this.botao.setAttribute('aria-expanded', String(!recolhida));
      } else {
        const aberta = document.body.classList.toggle('sge-lateral-aberta');
        this.botao.setAttribute('aria-expanded', String(aberta));
        this.sincronizarSobreposicao();
      }
    },

    fechar() {
      if (!document.body.classList.contains('sge-lateral-aberta')) return;
      document.body.classList.remove('sge-lateral-aberta');
      this.botao?.setAttribute('aria-expanded', 'false');
      this.sincronizarSobreposicao();
    },

    sincronizarSobreposicao() {
      if (!this.sobreposicao) return;
      // `hidden` mantem a camada fora da arvore de acessibilidade quando
      // invisivel, evitando que leitores de tela a anunciem.
      this.sobreposicao.hidden = !document.body.classList.contains('sge-lateral-aberta');
    },
  };

  /* ==================================================================== */
  /* 2. Confirmacao de acoes destrutivas                                  */
  /* ==================================================================== */
  const Confirmacao = {
    iniciar() {
      this.elemento = $('#modalConfirmacao');
      if (!this.elemento || !window.bootstrap) return;

      this.modal = new bootstrap.Modal(this.elemento);
      this.titulo = $('#modalConfirmacaoTitulo');
      this.texto = $('#modalConfirmacaoTexto');
      this.botao = $('#modalConfirmacaoBotao');
      this.acaoPendente = null;

      this.botao.addEventListener('click', () => {
        const acao = this.acaoPendente;
        this.acaoPendente = null;
        this.modal.hide();
        acao?.();
      });

      // Delegacao de evento: funciona tambem para conteudo inserido depois.
      document.addEventListener('click', (evento) => {
        const gatilho = evento.target.closest('[data-confirmar]');
        if (!gatilho) return;

        evento.preventDefault();
        evento.stopPropagation();
        this.solicitar(gatilho);
      });
    },

    solicitar(gatilho) {
      const dados = gatilho.dataset;
      this.titulo.textContent = dados.confirmarTitulo || 'Confirmar acao';
      this.texto.textContent =
        dados.confirmarTexto || 'Tem certeza que deseja continuar?';
      this.botao.textContent = dados.confirmarBotao || 'Confirmar';
      this.botao.className = `btn btn-${dados.confirmarCor || 'danger'}`;

      this.acaoPendente = () => {
        if (gatilho.tagName === 'FORM') {
          gatilho.submit();
        } else if (gatilho.form) {
          gatilho.form.submit();
        } else if (gatilho.href) {
          window.location.href = gatilho.href;
        }
      };

      this.modal.show();
    },
  };

  /* ==================================================================== */
  /* 3. Mascaras de entrada (padrao brasileiro)                           */
  /* ==================================================================== */
  const Mascaras = {
    formatadores: {
      cpf: (v) => apenasDigitos(v).slice(0, 11)
        .replace(/(\d{3})(\d)/, '$1.$2')
        .replace(/(\d{3})(\d)/, '$1.$2')
        .replace(/(\d{3})(\d{1,2})$/, '$1-$2'),

      cnpj: (v) => apenasDigitos(v).slice(0, 14)
        .replace(/(\d{2})(\d)/, '$1.$2')
        .replace(/(\d{3})(\d)/, '$1.$2')
        .replace(/(\d{3})(\d)/, '$1/$2')
        .replace(/(\d{4})(\d{1,2})$/, '$1-$2'),

      telefone: (v) => {
        const d = apenasDigitos(v).slice(0, 11);
        if (d.length <= 10) {
          return d.replace(/(\d{2})(\d)/, '($1) $2').replace(/(\d{4})(\d{1,4})$/, '$1-$2');
        }
        return d.replace(/(\d{2})(\d)/, '($1) $2').replace(/(\d{5})(\d{1,4})$/, '$1-$2');
      },

      cep: (v) => apenasDigitos(v).slice(0, 8).replace(/(\d{5})(\d{1,3})$/, '$1-$2'),
    },

    iniciar() {
      $$('[data-mascara]').forEach((campo) => {
        const formatar = this.formatadores[campo.dataset.mascara];
        if (!formatar) return;

        // Aplica na carga para normalizar valores vindos do banco.
        if (campo.value) campo.value = formatar(campo.value);

        campo.addEventListener('input', () => {
          const posicao = campo.selectionStart;
          const tamanhoAntes = campo.value.length;
          campo.value = formatar(campo.value);
          // Corrige o cursor apos a insercao dos separadores.
          const diferenca = campo.value.length - tamanhoAntes;
          if (posicao !== null && posicao < tamanhoAntes) {
            campo.setSelectionRange(posicao + diferenca, posicao + diferenca);
          }
        });
      });
    },
  };

  /* ==================================================================== */
  /* 4. Campos de senha: exibir/ocultar e medidor de forca                */
  /* ==================================================================== */
  const Senha = {
    iniciar() {
      this.montarAlternadores();
      this.montarMedidores();
    },

    montarAlternadores() {
      $$('[data-alternar-senha]').forEach((botao) => {
        botao.addEventListener('click', () => {
          const campo = $(`#${botao.dataset.alternarSenha}`);
          if (!campo) return;

          const oculto = campo.type === 'password';
          campo.type = oculto ? 'text' : 'password';
          botao.innerHTML = `<i class="bi bi-eye${oculto ? '-slash' : ''}"></i>`;
          botao.setAttribute('aria-label', oculto ? 'Ocultar senha' : 'Exibir senha');
          campo.focus();
        });
      });
    },

    montarMedidores() {
      $$('[data-forca-senha]').forEach((campo) => {
        const alvo = $(`#${campo.dataset.forcaSenha}`);
        if (!alvo) return;

        const barra = $('.sge-forca-senha__barra', alvo);
        const rotulo = $('[data-forca-rotulo]', alvo);

        campo.addEventListener('input', () => {
          const { percentual, cor, texto } = this.avaliar(campo.value);
          if (barra) {
            barra.style.width = `${percentual}%`;
            barra.style.background = cor;
          }
          if (rotulo) {
            rotulo.textContent = texto;
            rotulo.style.color = cor;
          }
        });
      });
    },

    /**
     * Avaliacao apenas indicativa para o usuario.
     * A politica que efetivamente aprova ou rejeita a senha e a do servidor
     * (`app/utils/seguranca.py`), que nao pode ser contornada.
     */
    avaliar(senha) {
      if (!senha) return { percentual: 0, cor: '#e5e7eb', texto: '' };

      let pontos = 0;
      if (senha.length >= 8) pontos += 1;
      if (senha.length >= 12) pontos += 1;
      if (/[a-z]/.test(senha) && /[A-Z]/.test(senha)) pontos += 1;
      if (/\d/.test(senha)) pontos += 1;
      if (/[^A-Za-z0-9]/.test(senha)) pontos += 1;

      const niveis = [
        { percentual: 20, cor: '#e02424', texto: 'Muito fraca' },
        { percentual: 40, cor: '#e02424', texto: 'Fraca' },
        { percentual: 60, cor: '#c27803', texto: 'Razoavel' },
        { percentual: 80, cor: '#057a55', texto: 'Boa' },
        { percentual: 100, cor: '#057a55', texto: 'Forte' },
      ];
      return niveis[Math.min(pontos, niveis.length) - 1] ?? niveis[0];
    },
  };

  /* ==================================================================== */
  /* 5. Formularios: envio unico e aviso de alteracoes nao salvas         */
  /* ==================================================================== */
  const Formularios = {
    iniciar() {
      this.evitarEnvioDuplicado();
      this.avisarAlteracoesPendentes();
      this.focarPrimeiroErro();
    },

    /** Cliques repetidos no botao criariam registros duplicados no banco. */
    evitarEnvioDuplicado() {
      $$('form:not([data-permitir-reenvio])').forEach((form) => {
        form.addEventListener('submit', () => {
          if (form.dataset.enviando === '1') return;
          form.dataset.enviando = '1';

          $$('button[type="submit"], input[type="submit"]', form).forEach((botao) => {
            const rotuloOriginal = botao.innerHTML;
            botao.disabled = true;
            botao.innerHTML =
              '<span class="spinner-border spinner-border-sm me-2" aria-hidden="true"></span>Aguarde...';

            // Se a validacao do navegador barrar o envio, restaura o botao.
            setTimeout(() => {
              if (!form.checkValidity()) {
                botao.disabled = false;
                botao.innerHTML = rotuloOriginal;
                form.dataset.enviando = '0';
              }
            }, 60);
          });
        });
      });
    },

    /** Impede perda acidental de um cadastro longo preenchido pela secretaria. */
    avisarAlteracoesPendentes() {
      $$('form[data-avisar-saida]').forEach((form) => {
        let alterado = false;

        form.addEventListener('input', () => { alterado = true; });
        form.addEventListener('submit', () => { alterado = false; });

        window.addEventListener('beforeunload', (evento) => {
          if (!alterado) return;
          evento.preventDefault();
          evento.returnValue = '';
        });
      });
    },

    /** Leva o usuario direto ao campo com problema apos uma validacao. */
    focarPrimeiroErro() {
      const campo = $('.is-invalid');
      if (!campo) return;
      campo.focus({ preventScroll: true });
      campo.scrollIntoView({ behavior: 'smooth', block: 'center' });
    },
  };

  /* ==================================================================== */
  /* 6. Filtro instantaneo de tabelas                                     */
  /* ==================================================================== */
  const FiltroTabela = {
    iniciar() {
      $$('[data-filtrar-tabela]').forEach((campo) => {
        const tabela = $(`#${campo.dataset.filtrarTabela}`);
        if (!tabela) return;

        const contador = campo.dataset.filtrarContador
          ? $(`#${campo.dataset.filtrarContador}`)
          : null;

        const filtrar = debounce(() => {
          const termo = semAcentos(campo.value.trim());
          let visiveis = 0;

          $$('tbody tr', tabela).forEach((linha) => {
            if (linha.dataset.semResultado === '1') return;
            const combina = !termo || semAcentos(linha.textContent).includes(termo);
            linha.hidden = !combina;
            if (combina) visiveis += 1;
          });

          if (contador) contador.textContent = visiveis;

          const linhaVazia = $('tr[data-sem-resultado]', tabela);
          if (linhaVazia) linhaVazia.hidden = visiveis > 0;
        }, 180);

        campo.addEventListener('input', filtrar);
      });
    },
  };

  /* ==================================================================== */
  /* 7. Selecao multipla em listagens                                     */
  /* ==================================================================== */
  const SelecaoMultipla = {
    iniciar() {
      $$('[data-selecionar-todos]').forEach((principal) => {
        const grupo = principal.dataset.selecionarTodos;
        const itens = () => $$(`input[type="checkbox"][data-grupo="${grupo}"]`);
        const barra = $(`[data-barra-selecao="${grupo}"]`);
        const contador = barra ? $('[data-contador-selecao]', barra) : null;

        const atualizar = () => {
          const marcados = itens().filter((i) => i.checked);
          principal.checked = marcados.length > 0 && marcados.length === itens().length;
          principal.indeterminate =
            marcados.length > 0 && marcados.length < itens().length;
          if (barra) barra.hidden = marcados.length === 0;
          if (contador) contador.textContent = marcados.length;
        };

        principal.addEventListener('change', () => {
          itens().forEach((item) => { item.checked = principal.checked; });
          atualizar();
        });

        itens().forEach((item) => item.addEventListener('change', atualizar));
        atualizar();
      });
    },
  };

  /* ==================================================================== */
  /* 8. Componentes do Bootstrap e ajustes gerais                         */
  /* ==================================================================== */
  const Interface = {
    iniciar() {
      if (window.bootstrap) {
        $$('[data-bs-toggle="tooltip"]').forEach((el) => new bootstrap.Tooltip(el));
        $$('[data-bs-toggle="popover"]').forEach((el) => new bootstrap.Popover(el));
      }

      // Mensagens de sucesso somem sozinhas; erros permanecem ate o usuario
      // fechar, para que nenhuma falha passe despercebida.
      $$('.alert-success, .alert-info').forEach((alerta) => {
        setTimeout(() => {
          if (window.bootstrap) bootstrap.Alert.getOrCreateInstance(alerta).close();
        }, 6000);
      });

      // Envio automatico dos filtros de listagem ao trocar um select.
      $$('[data-enviar-ao-mudar]').forEach((campo) => {
        campo.addEventListener('change', () => campo.form?.submit());
      });

      // Impressao direta a partir de um botao.
      $$('[data-imprimir]').forEach((botao) => {
        botao.addEventListener('click', () => window.print());
      });
    },
  };

  /* ==================================================================== */
  /* 9. Requisicoes JSON com CSRF                                         */
  /* ==================================================================== */
  /**
   * Wrapper de `fetch` que injeta o token CSRF e trata erros de forma
   * uniforme. Exposto em `window.SGE` para uso pelas paginas.
   */
  async function requisitar(url, opcoes = {}) {
    const configuracao = {
      credentials: 'same-origin',
      headers: {
        'X-Requested-With': 'XMLHttpRequest',
        ...(opcoes.headers || {}),
      },
      ...opcoes,
    };

    const metodo = (opcoes.method || 'GET').toUpperCase();
    if (!['GET', 'HEAD', 'OPTIONS'].includes(metodo)) {
      configuracao.headers['X-CSRFToken'] = obterTokenCSRF();
      if (opcoes.body && !(opcoes.body instanceof FormData)) {
        configuracao.headers['Content-Type'] = 'application/json';
      }
    }

    const resposta = await fetch(url, configuracao);
    const tipo = resposta.headers.get('content-type') || '';
    const dados = tipo.includes('application/json')
      ? await resposta.json()
      : await resposta.text();

    if (!resposta.ok) {
      throw new Error(dados?.erro || `Erro ${resposta.status}`);
    }
    return dados;
  }

  /* ==================================================================== */
  /* Inicializacao                                                        */
  /* ==================================================================== */
  function iniciar() {
    BarraLateral.iniciar();
    Confirmacao.iniciar();
    Mascaras.iniciar();
    Senha.iniciar();
    Formularios.iniciar();
    FiltroTabela.iniciar();
    SelecaoMultipla.iniciar();
    Interface.iniciar();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', iniciar);
  } else {
    iniciar();
  }

  // API publica usada pelas paginas (graficos, acoes assincronas).
  window.SGE = { $, $$, requisitar, debounce, semAcentos, apenasDigitos, obterTokenCSRF };
})();
