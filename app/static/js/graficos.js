/* ==========================================================================
   SGE - Graficos do painel e dos relatorios (Chart.js).

   Restricao de seguranca: a Content-Security-Policy do sistema define
   `script-src 'self'`, o que proibe qualquer <script> inline. Por isso os
   dados nao sao injetados como codigo: cada <canvas> declara os proprios
   dados em atributos `data-*` (serializados com `|tojson` no Jinja2) e este
   arquivo apenas os le e desenha.

   Ganho colateral: os dados ficam fora do HTML executavel, eliminando de vez
   a possibilidade de XSS por interpolacao de variavel dentro de <script>.
   ========================================================================== */

(() => {
  'use strict';

  if (typeof Chart === 'undefined') return;

  /* ------------------------------------------------------------------ */
  /* Paleta e padroes visuais                                           */
  /* ------------------------------------------------------------------ */
  const PALETA = [
    '#1a56db', '#057a55', '#c27803', '#e02424', '#7e3af2',
    '#0694a2', '#ff5a1f', '#5850ec', '#e74694', '#046c4e',
  ];

  const CINZA_GRADE = '#e5e7eb';
  const CINZA_TEXTO = '#6b7280';

  // Padroes globais coerentes com o design system.
  Chart.defaults.font.family =
    '"Segoe UI", -apple-system, BlinkMacSystemFont, Roboto, sans-serif';
  Chart.defaults.font.size = 12;
  Chart.defaults.color = CINZA_TEXTO;
  Chart.defaults.plugins.legend.labels.usePointStyle = true;
  Chart.defaults.plugins.legend.labels.boxWidth = 8;
  Chart.defaults.plugins.legend.labels.padding = 14;

  Chart.defaults.plugins.tooltip.backgroundColor = '#111827';
  Chart.defaults.plugins.tooltip.padding = 10;
  Chart.defaults.plugins.tooltip.cornerRadius = 6;
  Chart.defaults.plugins.tooltip.titleFont = { weight: '600' };
  Chart.defaults.plugins.tooltip.displayColors = false;

  /** Le e valida um atributo JSON do elemento. */
  function lerDados(elemento, atributo, padrao = []) {
    const bruto = elemento.dataset[atributo];
    if (!bruto) return padrao;
    try {
      const valor = JSON.parse(bruto);
      return Array.isArray(valor) || typeof valor === 'object' ? valor : padrao;
    } catch {
      return padrao;
    }
  }

  /** Exibe uma mensagem no lugar do grafico quando nao ha dados. */
  function marcarVazio(canvas) {
    const container = canvas.parentElement;
    if (!container) return;
    container.innerHTML = `
      <div class="sge-vazio h-100 d-flex flex-column justify-content-center">
        <i class="bi bi-bar-chart"></i>
        <p class="mb-0 small">Ainda nao ha dados suficientes para este grafico.</p>
      </div>`;
  }

  /** Eixo Y sem casas decimais: contagens sao sempre inteiras. */
  const escalaContagem = {
    beginAtZero: true,
    ticks: { precision: 0 },
    grid: { color: CINZA_GRADE, drawBorder: false },
  };

  const escalaCategoria = {
    grid: { display: false, drawBorder: false },
  };

  /* ------------------------------------------------------------------ */
  /* Construtores por tipo                                              */
  /* ------------------------------------------------------------------ */
  const construtores = {
    /** Barras verticais — distribuicoes por categoria. */
    barras(canvas, rotulos, valores, opcoes) {
      return new Chart(canvas, {
        type: 'bar',
        data: {
          labels: rotulos,
          datasets: [{
            label: opcoes.rotuloSerie || 'Total',
            data: valores,
            backgroundColor: opcoes.cores || PALETA[0],
            borderRadius: 6,
            maxBarThickness: 46,
          }],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { display: false } },
          scales: { y: escalaContagem, x: escalaCategoria },
        },
      });
    },

    /** Barras horizontais — bom para rotulos longos (nomes de disciplina). */
    barrasHorizontais(canvas, rotulos, valores, opcoes) {
      return new Chart(canvas, {
        type: 'bar',
        data: {
          labels: rotulos,
          datasets: [{
            label: opcoes.rotuloSerie || 'Total',
            data: valores,
            backgroundColor: opcoes.cores || PALETA[1],
            borderRadius: 6,
            maxBarThickness: 26,
          }],
        },
        options: {
          indexAxis: 'y',
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { display: false } },
          scales: {
            x: { beginAtZero: true, grid: { color: CINZA_GRADE, drawBorder: false } },
            y: escalaCategoria,
          },
        },
      });
    },

    /** Rosca — composicao de um total (turnos, situacoes). */
    rosca(canvas, rotulos, valores, opcoes) {
      return new Chart(canvas, {
        type: 'doughnut',
        data: {
          labels: rotulos,
          datasets: [{
            data: valores,
            backgroundColor: opcoes.cores || PALETA,
            borderWidth: 2,
            borderColor: '#fff',
            hoverOffset: 6,
          }],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          cutout: '62%',
          plugins: {
            legend: { position: 'bottom' },
            tooltip: {
              displayColors: true,
              callbacks: {
                label(contexto) {
                  const total = contexto.dataset.data.reduce((a, b) => a + b, 0);
                  const parte = contexto.parsed;
                  const pct = total ? ((parte / total) * 100).toFixed(1) : '0';
                  return ` ${contexto.label}: ${parte} (${pct}%)`;
                },
              },
            },
          },
        },
      });
    },

    /** Linha — evolucao ao longo do tempo. */
    linha(canvas, rotulos, valores, opcoes) {
      return new Chart(canvas, {
        type: 'line',
        data: {
          labels: rotulos,
          datasets: [{
            label: opcoes.rotuloSerie || 'Total',
            data: valores,
            borderColor: PALETA[0],
            backgroundColor: 'rgba(26, 86, 219, 0.10)',
            borderWidth: 2,
            fill: true,
            tension: 0.35,
            pointRadius: 3,
            pointHoverRadius: 6,
            pointBackgroundColor: '#fff',
            pointBorderColor: PALETA[0],
            pointBorderWidth: 2,
          }],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { display: false } },
          scales: { y: escalaContagem, x: escalaCategoria },
          interaction: { mode: 'index', intersect: false },
        },
      });
    },
  };

  /* ------------------------------------------------------------------ */
  /* Inicializacao                                                      */
  /* ------------------------------------------------------------------ */
  function iniciar() {
    document.querySelectorAll('canvas[data-grafico]').forEach((canvas) => {
      const tipo = canvas.dataset.grafico;
      const construtor = construtores[tipo];
      if (!construtor) return;

      const rotulos = lerDados(canvas, 'rotulos', []);
      const valores = lerDados(canvas, 'valores', []);

      // Sem dados ou tudo zerado: um grafico vazio confunde mais do que ajuda.
      const temDados =
        rotulos.length > 0 &&
        valores.length > 0 &&
        valores.some((v) => Number(v) > 0);

      if (!temDados) {
        marcarVazio(canvas);
        return;
      }

      construtor(canvas, rotulos, valores, {
        cores: lerDados(canvas, 'cores', null) || undefined,
        rotuloSerie: canvas.dataset.rotuloSerie,
      });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', iniciar);
  } else {
    iniciar();
  }
})();
