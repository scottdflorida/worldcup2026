"""Brazilian Portuguese (pt-BR) client-side localisation.

A single generated asset — ``assets/i18n.js`` — carries an exact-match
dictionary plus a small set of anchored phrase rules, and runs a DOM walk that
swaps user-visible text and translatable attributes when the visitor toggles to
Portuguese.  English stays the source of truth in the generated HTML; this layer
is purely additive — any string with no dictionary entry and no matching rule
simply stays in English (graceful fallback).  A MutationObserver re-applies the
translation to content injected after load (live scores, the betting app), so
client-rendered UI is covered without touching app.js.

Single source of truth, per the build contract: edit the maps here, never the
generated ``assets/i18n.js``.
"""
import json
import os

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")

# --------------------------------------------------------------------------
# Country / national-team names.  Used both as standalone dictionary entries
# and by the compositional rules (flag-prefixed chips, "Watch <team>", odds
# tooltips, "Bet on <team>", …).
# --------------------------------------------------------------------------
COUNTRIES = {
    "Algeria": "Argélia",
    "Argentina": "Argentina",
    "Australia": "Austrália",
    "Austria": "Áustria",
    "Belgium": "Bélgica",
    "Bosnia & Herzegovina": "Bósnia e Herzegovina",
    "Bosnia and Herzegovina": "Bósnia e Herzegovina",
    "Brazil": "Brasil",
    "Canada": "Canadá",
    "Cape Verde": "Cabo Verde",
    "Colombia": "Colômbia",
    "Croatia": "Croácia",
    "Curaçao": "Curaçao",
    "Czech Republic": "República Tcheca",
    "DR Congo": "RD Congo",
    "Ecuador": "Equador",
    "Egypt": "Egito",
    "England": "Inglaterra",
    "France": "França",
    "Germany": "Alemanha",
    "Ghana": "Gana",
    "Haiti": "Haiti",
    "Iran": "Irã",
    "Iraq": "Iraque",
    "Ivory Coast": "Costa do Marfim",
    "Japan": "Japão",
    "Jordan": "Jordânia",
    "Mexico": "México",
    "Morocco": "Marrocos",
    "Netherlands": "Holanda",
    "New Zealand": "Nova Zelândia",
    "Norway": "Noruega",
    "Panama": "Panamá",
    "Paraguay": "Paraguai",
    "Portugal": "Portugal",
    "Qatar": "Catar",
    "Saudi Arabia": "Arábia Saudita",
    "Scotland": "Escócia",
    "Senegal": "Senegal",
    "South Africa": "África do Sul",
    "South Korea": "Coreia do Sul",
    "Spain": "Espanha",
    "Sweden": "Suécia",
    "Switzerland": "Suíça",
    "Tunisia": "Tunísia",
    "Turkey": "Turquia",
    "Uruguay": "Uruguai",
    "USA": "EUA",
    "Uzbekistan": "Uzbequistão",
}

# --------------------------------------------------------------------------
# Exact-match UI dictionary (English text node / attribute value -> pt-BR).
# Compositional strings (dates, scorelines, percentages, "Watch <team>", …)
# are handled by RULES in the runtime instead of being enumerated here.
# --------------------------------------------------------------------------
UI = {
    # ---- global chrome: nav, header, footer ----
    "Home": "Início",
    "Teams": "Seleções",
    "Bracket": "Chave",
    "Fantasy": "Fantasy",
    "Bets": "Apostas",
    "Calendar": "Calendário",
    "Skip to content": "Pular para o conteúdo",
    "Primary": "Principal",
    "World Cup 2026 tracker — home": "Painel da Copa do Mundo 2026 — início",
    "STAGE": "FASE",
    "UPDATED": "ATUALIZADO",
    "Live match-center · United States · Canada · Mexico":
        "Central de jogos ao vivo · Estados Unidos · Canadá · México",
    "Times shown in": "Horários em",
    "Display time zone": "Fuso horário de exibição",
    "Eastern · ET": "Leste · ET",
    "Central · CT": "Central · CT",
    "Mountain · MT": "Montanha · MT",
    "Pacific · PT": "Pacífico · PT",
    "Brazil · BRT": "Brasil · BRT",

    # ---- status words / chips ----
    "Group stage": "Fase de grupos",
    "group stage": "fase de grupos",
    "Knocked out": "Eliminado",
    "Won": "Vitória",
    "Lost": "Derrota",
    "Drew": "Empate",
    "Through": "Classificado",
    "Qualify": "Classifica",
    "qualify": "classifica",
    "On the bubble": "Na bolha",
    "eight advance": "oito avançam",
    "top-two line": "linha dos dois primeiros",
    "qualification line": "linha de classificação",
    "Best third-placed teams": "Melhores terceiros colocados",
    "8th-best cutoff": "corte do 8º melhor",
    "Eight third-placed teams advance to the Round of 32.":
        "Os oito melhores terceiros colocados avançam para a Rodada de 32.",
    "Status": "Situação",
    "Team": "Seleção",
    "GF": "GP",
    "GA": "GC",
    "GD": "SG",
    "Group complete": "Grupo encerrado",
    "Group winners": "1º do grupo",
    "Final standings": "Classificação final",
    "Group standings": "Classificação do grupo",
    "Knocked out of the tournament": "Eliminado do torneio",
    "Through as a best third": "Classificado como um dos melhores terceiros",
    "on the bubble": "na bolha",
    "3rd hope": "vaga de 3º",
    "current track": "trajeto atual",
    "IN": "DENTRO",
    "OUT": "FORA",
    "Out": "Fora",
    "out": "fora",
    "BUBBLE": "BOLHA",
    "✓ in": "✓ dentro",
    "NOW": "AGORA",
    "now": "agora",
    "LIVE": "AO VIVO",
    "FT": "FIM",
    "Next": "Próximo",
    "Last": "Último",
    "Grp": "Gru",
    "vs": "x",

    # ---- home ----
    # Hero headline, set across styled spans: "THE 2026 / WORLD CUP / IS [LIVE]"
    # -> "A COPA DO / MUNDO 2026 / ESTÁ [AO VIVO]".  The brand wordmark (which
    # also reads "WORLD CUP") carries data-no-i18n, so this only hits the hero.
    "THE\xa02026": "A COPA DO",
    "WORLD\xa0CUP": "MUNDO 2026",
    "IS": "ESTÁ",
    "Matchday pulse": "Pulso da rodada",
    "Tournament status": "Situação do torneio",
    "TOURNAMENT\xa0PROGRESS": "PROGRESSO\xa0DO\xa0TORNEIO",
    "The twelve groups": "Os doze grupos",
    "Tap a group for fixtures & scenarios": "Toque em um grupo para jogos e cenários",
    "Best third-placed race": "Disputa pelos melhores terceiros",
    "Race\xa0to\xa08th": "Disputa\xa0pelo\xa08º",
    "Your teams": "Suas seleções",
    "Standings": "Classificação",
    "Scenarios": "Cenários",
    "Wins group": "Vence o grupo",
    "Coming up": "A seguir",
    "Upcoming": "Próximos",
    "Kicks off": "Começa",
    "Kicks off …": "Começa …",
    "Loading…": "Carregando…",
    "Each bar splits a team's remaining finishes into":
        "Cada barra divide os finais possíveis de cada seleção em",
    "how the remaining games could finish the table":
        "como os jogos restantes podem fechar a tabela",
    "Pin any team with ★ — next & latest match, lit up everywhere":
        "Fixe qualquer seleção com ★ — próximo e último jogo, destacados em todo o site",
    "Tap a team to inspect its path to the final; ★ to follow it across the site.":
        "Toque em uma seleção para ver seu caminho até a final; ★ para acompanhá-la pelo site.",

    # ---- teams directory ----
    "All 48 teams": "Todas as 48 seleções",
    "All teams": "Todas",
    "Groups": "Grupos",
    "Search teams": "Buscar seleções",
    "Search any of 48 teams…": "Busque entre as 48 seleções…",
    "Team directory": "Diretório de seleções",
    "No teams match that search.": "Nenhuma seleção corresponde à busca.",

    # ---- bracket ----
    "Knockout bracket": "Chave do mata-mata",
    "Bracket rounds": "Fases da chave",
    "Round of 32": "Rodada de 32",
    "Round of 16": "Oitavas de final",
    "Quarter-final": "Quartas de final",
    "Quarter-finals": "Quartas de final",
    "Semi-final": "Semifinal",
    "Semi-finals": "Semifinais",
    "Round of 32 → Final as one connected tree. Pin teams with ★ to mark their path.":
        "Da Rodada de 32 até a Final em uma árvore conectada. Fixe seleções com ★ para marcar o caminho.",
    "Tap to pick a winner in every undecided tie — settled results are locked. Saved on this device.":
        "Toque para escolher o vencedor de cada confronto em aberto — resultados definidos ficam travados. Salvo neste dispositivo.",
    "Pick the winner": "Escolha o vencedor",
    "Pick winner": "Escolher vencedor",
    "Reset": "Limpar",
    "Current round:": "Rodada atual:",
    "World Champion": "Campeão Mundial",
    "Champion T.B.D.": "Campeão a definir",
    "KO\xa0odds": "Chance\xa0KO",
    "Close": "Fechar",
    "; the figure on the right is the chance of reaching the knockouts. The group is decided — these reflect the live knockout picture.":
        "; o número à direita é a chance de chegar ao mata-mata. O grupo está definido — estes refletem o quadro atual do mata-mata.",

    # ---- calendar ----
    "Match calendar": "Calendário de jogos",
    "Tournament calendar": "Calendário do torneio",
    "Every matchday in Pacific time — group stage to the Final.":
        "Todas as rodadas no horário do Pacífico — da fase de grupos à Final.",
    "Upcoming games": "Próximos jogos",
    "Upcoming matches": "Próximos jogos",
    "Completed games": "Jogos encerrados",
    "Match for third place": "Disputa de terceiro lugar",

    # ---- group pages ----
    "live table · advance odds as a tally": "tabela ao vivo · chances de avanço em barras",
    "reach knockouts →": "chegar ao mata-mata →",
    "(top two),": "(dois primeiros),",
    "(third-place hope) and": "(esperança de 3º) e",

    # ---- fantasy ----
    "Fantasy bracket": "Chave do Fantasy",
    "Clear this pick": "Limpar escolha",
    "next four matches": "próximos quatro jogos",

    # ---- betting ----
    "Betting pool": "Bolão de apostas",
    "Place a bet": "Fazer uma aposta",
    "Place bet": "Apostar",
    "Pool code": "Código do bolão",
    "Display name": "Nome de exibição",
    "Join a pool": "Entrar em um bolão",
    "Join another pool": "Entrar em outro bolão",
    "Pick a display name and a pool code. Share the code so everyone is in the same "
    "pool. A new code starts a new pool. Already joined? Enter the same name and code "
    "to pick up where you left off — even on a new device.":
        "Escolha um nome de exibição e um código de bolão. Compartilhe o código para "
        "todos ficarem no mesmo bolão. Um código novo cria um bolão novo. Já entrou? "
        "Digite o mesmo nome e código para retomar de onde parou — até em outro dispositivo.",
    "Open matches": "Jogos em aberto",
    "Closed matches": "Jogos encerrados",
    "In-play matches": "Jogos em andamento",
    "Leaderboard": "Ranking",
    "Remove bet": "Remover aposta",
    "Save changes": "Salvar alterações",
    "Edit bet": "Editar aposta",
    "See team details": "Ver detalhes da seleção",
    "Show everyone’s bets": "Mostrar as apostas de todos",
    "Could not join.": "Não foi possível entrar.",
    "Could not place bet.": "Não foi possível fazer a aposta.",
    "Could not update.": "Não foi possível atualizar.",
    "Could not remove.": "Não foi possível remover.",
    "Could not reach the betting service.":
        "Não foi possível conectar ao serviço de apostas.",
    "The betting pool is not set up on the server yet.":
        "O bolão ainda não foi configurado no servidor.",
    "Enter a name and a code.": "Informe um nome e um código.",
    "Enter a stake.": "Informe um valor.",
    "Not enough balance.": "Saldo insuficiente.",
    "More than you have.": "Mais do que você tem.",
    "That is more than you have.": "Isso é mais do que você tem.",
    "That is more than your balance.": "Isso é mais do que seu saldo.",
    "That name is taken in this pool.": "Esse nome já está em uso neste bolão.",
    "This match has kicked off.": "Este jogo já começou.",
    "Betting on this match is closed.": "As apostas para este jogo estão encerradas.",
    "You already backed the other side here.":
        "Você já apostou no outro lado aqui.",
    "You already backed the other side of this match.":
        "Você já apostou no outro lado deste jogo.",
    "and it locks in here, marked in vermilion across the whole site.":
        "e fica fixado aqui, destacado em vermelho em todo o site.",
    "Play money. Everyone starts with $100, bet any amount on who wins each "
    "knockout match, payouts at the listed odds. Hit $0 and you're out.":
        "Dinheiro de mentira. Todo mundo começa com $100, aposte qualquer valor em "
        "quem vence cada jogo do mata-mata, com pagamento pelas odds listadas. "
        "Zerou, está fora.",

    # ---- team page ----
    "Squad": "Elenco",
    "Goalkeepers": "Goleiros",
    "Defenders": "Defensores",
    "Midfielders": "Meio-campistas",
    "Forwards": "Atacantes",
    "current squad by position": "elenco atual por posição",
    "bold": "negrito",
    "Road to the final": "Caminho até a final",
    "Results": "Resultados",
    "Remaining group games": "Jogos restantes do grupo",
    "Next knockout match": "Próximo jogo do mata-mata",
    "Win the group": "Vencer o grupo",
    "Finish runner-up": "Terminar em segundo",
    "Knocked out — the road ends in the group stage this time.":
        "Eliminado — o caminho termina na fase de grupos desta vez.",
    "No knockout path yet — the bracket opens once the group stage ends.":
        "Ainda sem caminho no mata-mata — a chave abre quando a fase de grupos terminar.",
    "your team highlighted · advance odds as a tally":
        "sua seleção destacada · chances de avanço em barras",
}


def _load_json(name):
    path = os.path.join(DATA_DIR, name)
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _blurbs_pt():
    """pt-BR blurb translations keyed by the exact English blurb text.

    Joins the English cache (blurbs.json) with the pt cache (blurbs.pt.json) by
    team, and only emits a translation whose fingerprint still matches the live
    English blurb — so a blurb regenerated since its last translation falls back
    to English instead of showing a stale pt version."""
    en = _load_json("blurbs.json")
    pt = _load_json("blurbs.pt.json")
    out = {}
    for team, e in en.items():
        p = pt.get(team)
        if not p or p.get("fingerprint") != e.get("fingerprint"):
            continue
        en_text, pt_text = e.get("text"), p.get("text")
        if en_text and pt_text:
            out[en_text] = pt_text
    return out


def _full_dict():
    d = {}
    d.update(COUNTRIES)
    d.update(UI)
    d.update(_blurbs_pt())
    return d


# --------------------------------------------------------------------------
# Runtime.  DICT / COUNTRIES are injected as JSON; the phrase rules live here
# in JS because they need capture groups and the country map.
# --------------------------------------------------------------------------
_RUNTIME = r"""/* World Cup 2026 — pt-BR localisation (generated from wc/i18n.py; do not edit). */
(function () {
  "use strict";
  var DICT = __DICT__;
  var C = __COUNTRIES__;
  for (var k in C) { if (!DICT.hasOwnProperty(k)) DICT[k] = C[k]; }

  // Whitespace-collapsed index, for multi-line / oddly-spaced source nodes.
  var COLLAPSED = {};
  for (var key in DICT) { COLLAPSED[key.replace(/\s+/g, " ").trim()] = DICT[key]; }

  var ATTRS = ["aria-label", "title", "placeholder", "alt"];
  var WD = {Mon:"Seg",Tue:"Ter",Wed:"Qua",Thu:"Qui",Fri:"Sex",Sat:"Sáb",Sun:"Dom"};
  var MON = {Jan:"Jan",Feb:"Fev",Mar:"Mar",Apr:"Abr",May:"Mai",Jun:"Jun",
             Jul:"Jul",Aug:"Ago",Sep:"Set",Oct:"Out",Nov:"Nov",Dec:"Dez"};
  var RES = {W:"V",D:"E",L:"D"};          // Win/Draw/Loss -> Vitória/Empate/Derrota
  var ORD = {"1st":"1º","2nd":"2º","3rd":"3º","4th":"4º"};
  function pc(n){ return C[n] || n; }
  function ord(o){ return ORD[o] || o; }

  var RULES = [
    // "Fri Jul 3" -> "Sex 3 Jul"
    function (s) { var m = s.match(/^(Mon|Tue|Wed|Thu|Fri|Sat|Sun) (Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) (\d{1,2})$/);
      return m ? WD[m[1]] + " " + m[3] + " " + MON[m[2]] : null; },
    // bare weekday
    function (s) { return WD.hasOwnProperty(s) ? WD[s] : null; },
    // footer updated stamp: "Jun 30, 2026 · 13:33 UTC" -> "30 Jun 2026 · 13:33 UTC"
    function (s) { var m = s.match(/^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) (\d{1,2}), (\d{4}) · (.+)$/);
      return m ? m[2] + " " + MON[m[1]] + " " + m[3] + " · " + m[4] : null; },
    // result chip "W 2–1" -> "V 2–1"
    function (s) { var m = s.match(/^([WDL]) (\d+[–-]\d+)$/);
      return m ? RES[m[1]] + " " + m[2] : null; },
    // "2–3 pens" -> "2–3 pênaltis"
    function (s) { var m = s.match(/^(\d+[–-]\d+) pens$/);
      return m ? m[1] + " pênaltis" : null; },
    // "Watch Brazil" -> "Seguir Brasil"
    function (s) { var m = s.match(/^Watch (.+)$/);
      return m ? "Seguir " + pc(m[1]) : null; },
    // "Watching" star label
    function (s) { return s === "Watch" ? "Seguir" : (s === "Watching" ? "Seguindo" : null); },
    // "50% IN" / "0% OUT" / "100% BUBBLE"
    function (s) { var m = s.match(/^(\d+)% (IN|OUT|BUBBLE)$/); if (!m) return null;
      var t = {IN:"DENTRO", OUT:"FORA", BUBBLE:"BOLHA"}; return m[1] + "% " + t[m[2]]; },
    // full odds tooltip, optionally "<team>: " prefixed
    function (s) { var m = s.match(/^(?:(.+): )?(\d+)% qualify directly, (\d+)% on the third-place bubble, (\d+)% out — (\d+)% chance to reach the knockouts$/);
      if (!m) return null; var pre = m[1] ? pc(m[1]) + ": " : "";
      return pre + m[2] + "% classificam direto, " + m[3] + "% na disputa de melhor terceiro, "
        + m[4] + "% fora — " + m[5] + "% de chance de chegar ao mata-mata"; },
    function (s) { var m = s.match(/^(\d+)% chance to reach the knockouts$/);
      return m ? m[1] + "% de chance de chegar ao mata-mata" : null; },
    // calendar "3 possible"
    function (s) { var m = s.match(/^(\d+) possible$/);
      return m ? m[1] + " possíveis" : null; },
    // "76 of 104 matches played"
    function (s) { var m = s.match(/^(\d+) of (\d+) matches played$/);
      return m ? m[1] + " de " + m[2] + " jogos disputados" : null; },
    // "76/104 played"
    function (s) { var m = s.match(/^(\d+)\/(\d+) played$/);
      return m ? m[1] + "/" + m[2] + " disputados" : null; },
    // home sub: "latest results, then next kickoffs · 76/104 played"
    function (s) { var m = s.match(/^latest results, then next kickoffs · (\d+)\/(\d+) played$/);
      return m ? "resultados recentes, depois os próximos jogos · " + m[1] + "/" + m[2] + " disputados" : null; },
    // "Group A" -> "Grupo A"
    function (s) { var m = s.match(/^Group ([A-L])$/);
      return m ? "Grupo " + m[1] : null; },
    // "Group A standings" -> "Classificação do Grupo A"
    function (s) { var m = s.match(/^Group ([A-L]) standings$/);
      return m ? "Classificação do Grupo " + m[1] : null; },
    // "Group A winners" -> "1º do Grupo A"  /  "Group A runners-up" -> "2º do Grupo A"
    function (s) { var m = s.match(/^Group ([A-L]) winners$/);
      return m ? "1º do Grupo " + m[1] : null; },
    function (s) { var m = s.match(/^Group ([A-L]) runners-up$/);
      return m ? "2º do Grupo " + m[1] : null; },
    // team-card meta "Group A · 1st · 9 pts"
    function (s) { var m = s.match(/^Group ([A-L]) · (1st|2nd|3rd|4th) · (\d+) pts$/);
      return m ? "Grupo " + m[1] + " · " + ord(m[2]) + " · " + m[3] + " pts" : null; },
    // hero line: "· 1st place · 5 pts (1W 2D 0L)"
    function (s) { var m = s.match(/^· (1st|2nd|3rd|4th) place · (\d+) pts \((\d+)W (\d+)D (\d+)L\)$/);
      return m ? "· " + ord(m[1]) + " lugar · " + m[2] + " pts (" + m[3] + "V " + m[4] + "E " + m[5] + "D)" : null; },
    // outlook one-liners (team pages)
    function (s) { var m = s.match(/^Out of contention in Group ([A-L])\.$/);
      return m ? "Fora de combate no Grupo " + m[1] + "." : null; },
    function (s) { var m = s.match(/^Qualified for the Round of 32 from Group ([A-L])\.$/);
      return m ? "Classificado para a Rodada de 32 pelo Grupo " + m[1] + "." : null; },
    function (s) { var m = s.match(/^Through to the Round of 32 as Group ([A-L]) winners\.$/);
      return m ? "Classificado para a Rodada de 32 como 1º do Grupo " + m[1] + "." : null; },
    function (s) { var m = s.match(/^3rd in Group ([A-L]) — chasing a best-third-place spot\.$/);
      return m ? "3º no Grupo " + m[1] + " — brigando por uma vaga de melhor terceiro." : null; },
    // watchlist tooltip "Pin Brazil to your watchlist" -> "Fixar Brasil na sua lista"
    function (s) { var m = s.match(/^Pin (.+) to your watchlist$/);
      return m ? "Fixar " + pc(m[1]) + " na sua lista" : null; },
    // "potential futures — who Brazil could meet each round"
    function (s) { var m = s.match(/^potential futures — who (.+) could meet each round$/);
      return m ? "futuros possíveis — quem " + pc(m[1]) + " pode enfrentar a cada fase" : null; },
    // squad caption: "starting XI from 2026-06-29 in"
    function (s) { var m = s.match(/^starting XI from (.+) in$/);
      return m ? "escalação titular de " + m[1] + " em" : null; },
    // "Bet on Brazil" -> "Apostar em Brasil"
    function (s) { var m = s.match(/^Bet on (.+)$/);
      return m ? "Apostar em " + pc(m[1]) : null; },
    // "Returns $250.00 if Brazil wins" -> "Retorna $250.00 se Brasil vencer"
    function (s) { var m = s.match(/^Returns (.+) if (.+) wins$/);
      return m ? "Retorna " + m[1] + " se " + pc(m[2]) + " vencer" : null; },
    // leaderboard subline "cash $100 · in play $50" -> "saldo $100 · em jogo $50"
    function (s) { var m = s.match(/^cash (.+) · in play (.+)$/);
      return m ? "saldo " + m[1] + " · em jogo " + m[2] : null; },
    // bracket slot labels
    function (s) { var m = s.match(/^Winner M(\d+)$/); return m ? "Vencedor M" + m[1] : null; },
    function (s) { var m = s.match(/^Loser M(\d+)$/);  return m ? "Perdedor M" + m[1] : null; },
    function (s) { var m = s.match(/^Winner ([A-L])$/);   return m ? "1º " + m[1] : null; },
    function (s) { var m = s.match(/^Runner-up ([A-L])$/); return m ? "2º " + m[1] : null; },
    function (s) { var m = s.match(/^3rd ([A-L](?:\/[A-L])*)$/); return m ? "3º " + m[1] : null; },
    // flag-prefixed chip: "🇫🇷 France" -> "🇫🇷 França"
    function (s) { var m = s.match(/^(\S+?[  \s])([A-Za-zÀ-ÿ'’ .&-]+)$/);
      return (m && C[m[2]]) ? m[1] + C[m[2]] : null; }
  ];

  function translate(raw) {
    if (raw == null) return null;
    var t = raw.trim();
    if (!t) return null;
    var pt = null;
    if (DICT.hasOwnProperty(t)) pt = DICT[t];
    if (pt == null) { for (var i = 0; i < RULES.length; i++) { pt = RULES[i](t); if (pt != null) break; } }
    if (pt == null) { var col = t.replace(/\s+/g, " "); if (COLLAPSED.hasOwnProperty(col)) pt = COLLAPSED[col]; }
    if (pt == null || pt === t) return null;
    var i2 = raw.indexOf(t);                       // re-wrap with original surrounding whitespace
    return raw.slice(0, i2) + pt + raw.slice(i2 + t.length);
  }

  // ---- DOM application ---------------------------------------------------
  var touchedText = [];   // {node, en}
  var touchedAttr = [];   // {el, attr, en}
  var current = "en";
  var applying = false;
  var obs = null;
  var SKIP = {SCRIPT:1, STYLE:1, NOSCRIPT:1, TEMPLATE:1};

  function transText(node) {
    var pt = translate(node.nodeValue);
    if (pt != null) { touchedText.push({node: node, en: node.nodeValue}); node.nodeValue = pt; }
  }
  function transAttrs(el) {
    if (!el.getAttribute) return;
    for (var i = 0; i < ATTRS.length; i++) {
      var a = ATTRS[i];
      if (el.hasAttribute(a)) {
        var v = el.getAttribute(a), pt = translate(v);
        if (pt != null) { touchedAttr.push({el: el, attr: a, en: v}); el.setAttribute(a, pt); }
      }
    }
  }
  function walk(node) {
    if (node.nodeType === 3) { transText(node); return; }
    if (node.nodeType !== 1) return;
    var tag = node.tagName;
    if (SKIP[tag]) return;
    if (tag && tag.toLowerCase() === "svg") return;
    if (node.classList && node.classList.contains("lang-toggle")) return;
    if (node.hasAttribute && node.hasAttribute("data-no-i18n")) return;
    transAttrs(node);
    for (var c = node.firstChild; c; c = c.nextSibling) walk(c);
  }
  function restore() {
    var i;
    for (i = touchedText.length - 1; i >= 0; i--) touchedText[i].node.nodeValue = touchedText[i].en;
    for (i = touchedAttr.length - 1; i >= 0; i--) touchedAttr[i].el.setAttribute(touchedAttr[i].attr, touchedAttr[i].en);
    touchedText = []; touchedAttr = [];
  }
  function ensureObserver() {
    if (obs) return;
    obs = new MutationObserver(function (muts) {
      if (current !== "pt" || applying) return;
      applying = true;
      for (var i = 0; i < muts.length; i++) {
        var mu = muts[i];
        if (mu.type === "childList") { for (var j = 0; j < mu.addedNodes.length; j++) walk(mu.addedNodes[j]); }
        else if (mu.type === "characterData") transText(mu.target);
        else if (mu.type === "attributes") transAttrs(mu.target);
      }
      applying = false;
    });
    obs.observe(document.body, {childList: true, subtree: true, characterData: true,
                                attributes: true, attributeFilter: ATTRS});
  }

  function setUI() {
    var b = document.querySelectorAll(".lang-toggle .lt-btn");
    for (var i = 0; i < b.length; i++) {
      var on = b[i].getAttribute("data-lang") === current;
      b[i].setAttribute("aria-pressed", on ? "true" : "false");
      if (b[i].classList) b[i].classList.toggle("on", on);
    }
  }
  function apply(l) {
    if (l === current) { setUI(); return; }
    if (l === "pt") {
      current = "pt"; document.documentElement.lang = "pt-BR";
      applying = true; walk(document.body); applying = false; ensureObserver();
    } else {
      current = "en"; document.documentElement.lang = "en";
      applying = true; restore(); applying = false;
    }
    setUI();
  }
  function choose(l) { try { localStorage.setItem("wc26.lang", l); } catch (e) {} apply(l); }

  function init() {
    var saved = "en";
    try { saved = localStorage.getItem("wc26.lang") || "en"; } catch (e) {}
    document.addEventListener("click", function (e) {
      var t = e.target.closest && e.target.closest(".lang-toggle .lt-btn");
      if (t) { e.preventDefault(); choose(t.getAttribute("data-lang")); }
    });
    if (saved === "pt") apply("pt"); else setUI();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
"""


def build_js():
    """The full ``assets/i18n.js`` payload (dictionary + runtime)."""
    return (_RUNTIME
            .replace("__DICT__", json.dumps(_full_dict(), ensure_ascii=False))
            .replace("__COUNTRIES__", json.dumps(COUNTRIES, ensure_ascii=False)))


# Markup injected into the page header (single source for the toggle control).
TOGGLE_HTML = (
    '<div class="lang-toggle" data-no-i18n role="group" aria-label="Language / Idioma">'
    '<button type="button" class="lt-btn on" data-lang="en" aria-pressed="true">EN</button>'
    '<button type="button" class="lt-btn" data-lang="pt" aria-pressed="false">PT</button>'
    '</div>'
)
