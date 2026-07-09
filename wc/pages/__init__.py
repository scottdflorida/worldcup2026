"""Per-page builders. Each module owns one page (plus any data assembly it
needs); this package re-exports the builders render_site() calls."""
from .betting import betting_data, page_betting
from .bracket import page_bracket
from .calendar import page_calendar
from .fantasy import page_fantasy
from .group import page_group
from .home import page_home
from .team import page_team
from .teams import page_teams
