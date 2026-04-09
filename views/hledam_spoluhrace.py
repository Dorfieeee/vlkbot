"""
Hledam spoluhrace (LFP) feature using Discord v2 components.

Key design choice:
- No database is used.
- The visible message layout itself is the source of truth and is parsed back on interactions.

Requires discord.py 2.6+ for LayoutView, Section, TextDisplay, Label, and modal v2 components.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

import discord
from discord import app_commands

from config import GUILD_ID


PRAGUE_TZ = ZoneInfo("Europe/Prague")
DEFAULT_VOICE_CHANNEL_ID = 995772371120168960

COG_CUSTOM_ID_PREFIX = "lfp:cog:"
JOIN_ON_TIME_CUSTOM_ID = "lfp:join:ontime"
JOIN_LATE_CUSTOM_ID = "lfp:join:late"

TITLE_RE = re.compile(r"^## (?P<creator_name>.+) hledá spoluhráče\.\.\.$")
TIMESTAMP_RE = re.compile(r"<t:(?P<ts>\d+):[FRfDtT]>")
CHANNEL_RE = re.compile(r"<#(?P<channel_id>\d+)>")
CAPACITY_RE = re.compile(r"\*\*(?P<current>\d+)/(?P<capacity>\d+)\*\* hráčů")
PLAYER_ON_TIME_RE = re.compile(r"^<@(?P<uid>\d+)>$")
PLAYER_LATE_RE = re.compile(r"^<@(?P<uid>\d+)>(?: \*\((?P<note>.+)\)\*)?$")


def _message_view(message: discord.Message) -> discord.ui.LayoutView:
    return discord.ui.LayoutView.from_message(message, timeout=None)


def _extract_creator_id(message: discord.Message) -> int:
    view = _message_view(message)
    for component in view.walk_children():
        custom_id = getattr(component, "custom_id", None)
        if not isinstance(custom_id, str):
            continue

        if not custom_id.startswith(COG_CUSTOM_ID_PREFIX):
            continue

        return int(custom_id.removeprefix(COG_CUSTOM_ID_PREFIX))

    raise ValueError("Ve zprávě chybí identita autora události.")


def _text_displays_from_message(message: discord.Message) -> list[str]:
    view = _message_view(message)
    displays: list[str] = []
    for component in view.walk_children():
        if isinstance(component, discord.ui.TextDisplay):
            content = component.content
            displays.append(content)
    return displays


def _message_block_text(message_text: str) -> str:
    return f"Zpráva:\n{message_text}" if message_text else "Zpráva:\n-"


def _meta_block_text(
    *,
    event_ts: int,
    channel_id: int,
    guild_id: int,
    capacity: Optional[int],
    on_time: list[str],
    late: list[str],
) -> str:
    channel_link = f"https://discord.com/channels/{guild_id}/{channel_id}"
    lines = [
        f"Termín: <t:{event_ts}:F> · <t:{event_ts}:R>",
        f"Místo: <#{channel_id}> · [Připojit se]({channel_link})",
    ]
    if capacity is not None:
        lines.append(f"Kapacita: **{len(on_time) + len(late)}/{capacity}** hráčů")
    return "\n".join(lines)


def _players_block_text(on_time: list[str], late: list[str]) -> str:
    players = _players_text(on_time, late)
    return f"Hráči:\n{players}"


def _parse_message_block(message_block: str) -> str:
    if not message_block.startswith("Zpráva:\n"):
        raise ValueError("Nepodařilo se rozpoznat blok zprávy.")
    value = message_block.removeprefix("Zpráva:\n").strip()
    return "" if value == "-" else value


def _parse_meta_block(meta_text: str) -> tuple[int, int, Optional[int]]:
    timestamp_match = TIMESTAMP_RE.search(meta_text)
    channel_match = CHANNEL_RE.search(meta_text)

    if timestamp_match is None or channel_match is None:
        raise ValueError("Ve zprávě chybí datum nebo hlasový kanál.")

    event_ts = int(timestamp_match["ts"])
    channel_id = int(channel_match["channel_id"])

    capacity: Optional[int] = None
    capacity_match = CAPACITY_RE.search(meta_text)
    if capacity_match is not None:
        capacity = int(capacity_match["capacity"])

    return event_ts, channel_id, capacity


def _parse_players_block(players_block: str) -> tuple[list[str], list[str]]:
    if not players_block.startswith("Hráči:\n"):
        raise ValueError("Nepodařilo se rozpoznat blok hráčů.")

    players_text = players_block.removeprefix("Hráči:\n")
    stripped = players_text.strip()
    if not stripped or stripped == "*Zatím nikdo není přihlášený.*":
        return [], []

    on_time: list[str] = []
    late: list[str] = []

    for raw_line in players_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        on_time_match = PLAYER_ON_TIME_RE.match(line)
        if on_time_match is not None:
            on_time.append(on_time_match["uid"])
            continue

        late_match = PLAYER_LATE_RE.match(line)
        if late_match is not None:
            uid = late_match["uid"]
            note = late_match.group("note")
            late.append(f"{uid}|{note}" if note else uid)

    return on_time, late


def _state_from_message(message: discord.Message) -> dict[str, Any]:
    displays = _text_displays_from_message(message)
    if len(displays) < 4:
        raise ValueError("Zpráva nemá očekávanou strukturu komponent.")

    title_text = displays[0].strip()
    title_match = TITLE_RE.match(title_text)
    if title_match is None:
        raise ValueError("Nepodařilo se rozpoznat název události.")

    creator_id = _extract_creator_id(message)
    creator_name = title_match["creator_name"]
    message_text = _parse_message_block(displays[1])
    event_ts, channel_id, capacity = _parse_meta_block(displays[2])
    on_time, late = _parse_players_block(displays[3])

    cancelled = any("zrušena" in display.lower() for display in displays[4:])

    state: dict[str, Any] = {
        "cid": creator_id,
        "cn": creator_name,
        "msg": message_text,
        "ts": event_ts,
        "ch": channel_id,
        "ot": on_time,
        "lt": late,
    }
    if capacity is not None:
        state["cap"] = capacity
    if cancelled:
        state["x"] = 1
    return state


def _parse_czech_datetime(text: str) -> Optional[datetime]:
    for fmt in ("%d.%m.%Y %H:%M", "%d. %m. %Y %H:%M"):
        try:
            return datetime.strptime(text.strip(), fmt).replace(tzinfo=PRAGUE_TZ)
        except ValueError:
            continue
    return None


def _time_slot_values() -> list[str]:
    values: list[str] = []
    hour = 10
    minute = 0
    while True:
        values.append(f"{hour:02d}:{minute:02d}")
        if hour == 22 and minute == 0:
            break
        minute += 30
        if minute >= 60:
            minute = 0
            hour += 1
    return values


def _date_options(selected: str) -> list[discord.SelectOption]:
    return [
        discord.SelectOption(label="Dnes", value="today", default=selected == "today"),
        discord.SelectOption(label="Zítra", value="tomorrow", default=selected == "tomorrow"),
    ]


def _time_options(selected: str) -> list[discord.SelectOption]:
    return [
        discord.SelectOption(label=value, value=value, default=value == selected)
        for value in _time_slot_values()
    ]


def _event_datetime_from_selects(day_value: str, time_value: str) -> datetime:
    now = datetime.now(PRAGUE_TZ)
    target_date = now.date()
    if day_value == "tomorrow":
        target_date = target_date.fromordinal(target_date.toordinal() + 1)

    hour_text, minute_text = time_value.split(":", 1)
    return datetime(
        target_date.year,
        target_date.month,
        target_date.day,
        int(hour_text),
        int(minute_text),
        tzinfo=PRAGUE_TZ,
    )


def _uid_in(entries: list[str], uid: str) -> bool:
    return any(entry == uid or entry.startswith(f"{uid}|") for entry in entries)


def _remove_uid(entries: list[str], uid: str) -> list[str]:
    return [entry for entry in entries if not (entry == uid or entry.startswith(f"{uid}|"))]


def _players_text(on_time: list[str], late: list[str]) -> str:
    lines: list[str] = []

    for uid in on_time:
        lines.append(f"<@{uid}>")

    for entry in late:
        if "|" in entry:
            uid, note = entry.split("|", 1)
            lines.append(f"<@{uid}> *({note})*")
        else:
            lines.append(f"<@{entry}>")

    return "\n".join(lines) if lines else "*Zatím nikdo není přihlášený.*"


def _channel_default_value(channel_id: int) -> discord.SelectDefaultValue:
    return discord.SelectDefaultValue.from_channel(discord.Object(id=channel_id))


class LfpView(discord.ui.LayoutView):
    def __init__(self, *, state: dict[str, Any], guild_id: int) -> None:
        super().__init__(timeout=None)
        self.state = state
        self.guild_id = guild_id
        self._build()

    def _build(self) -> None:
        self.clear_items()

        creator_name = self.state["cn"]
        on_time = list(self.state.get("ot", []))
        late = list(self.state.get("lt", []))
        cancelled = bool(self.state.get("x"))

        cog_button = discord.ui.Button(
            emoji="⚙️",
            style=discord.ButtonStyle.secondary,
            custom_id=f"{COG_CUSTOM_ID_PREFIX}{self.state['cid']}",
        )
        cog_button.callback = self._cog_callback

        self.add_item(
            discord.ui.Section(
                discord.ui.TextDisplay(f"## {creator_name} hledá spoluhráče..."),
                accessory=cog_button,
            )
        )

        self.add_item(discord.ui.TextDisplay(_message_block_text(self.state.get("msg", ""))))
        self.add_item(
            discord.ui.TextDisplay(
                _meta_block_text(
                    event_ts=self.state["ts"],
                    channel_id=self.state["ch"],
                    guild_id=self.guild_id,
                    capacity=self.state.get("cap"),
                    on_time=on_time,
                    late=late,
                )
            )
        )

        self.add_item(discord.ui.Separator())
        self.add_item(discord.ui.TextDisplay(_players_block_text(on_time, late)))

        if cancelled:
            self.add_item(discord.ui.Separator())
            self.add_item(discord.ui.TextDisplay("❌ **Tato událost byla zrušena.**"))
        else:
            row = discord.ui.ActionRow()
            row.add_item(
                discord.ui.Button(
                    label="Přijdu včas",
                    style=discord.ButtonStyle.secondary,
                    custom_id=JOIN_ON_TIME_CUSTOM_ID,
                )
            )
            row.add_item(
                discord.ui.Button(
                    label="Přijdu o chvíli později",
                    style=discord.ButtonStyle.secondary,
                    custom_id=JOIN_LATE_CUSTOM_ID,
                )
            )
            self.add_item(row)

    async def _cog_callback(self, interaction: discord.Interaction) -> None:
        try:
            state = _state_from_message(interaction.message)
        except Exception:
            await interaction.response.send_message(
                "Nepodařilo se načíst stav události.", ephemeral=True
            )
            return

        if interaction.user.id != state["cid"]:
            await interaction.response.send_message(
                "Tuto událost může upravovat jen její autor.", ephemeral=True
            )
            return

        await interaction.response.send_message(
            "### Správa události",
            view=LfpManageView(source_message=interaction.message, state=state),
            ephemeral=True,
        )


class LfpCogItem(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"^lfp:cog:(?P<creator_id>\d+)$",
):
    def __init__(self, item: discord.ui.Button, creator_id: int) -> None:
        self.creator_id = creator_id
        super().__init__(item)

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
    ) -> "LfpCogItem":
        return cls(item, int(match["creator_id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            state = _state_from_message(interaction.message)
        except Exception:
            await interaction.response.send_message(
                "Nepodařilo se načíst stav události.", ephemeral=True
            )
            return

        if interaction.user.id != self.creator_id:
            await interaction.response.send_message(
                "Tuto událost může upravovat jen její autor.", ephemeral=True
            )
            return

        await interaction.response.send_message(
            "### Správa události",
            view=LfpManageView(source_message=interaction.message, state=state),
            ephemeral=True,
        )


class LfpJoinItem(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"^lfp:join:(?P<kind>ontime|late)$",
):
    def __init__(self, item: discord.ui.Button, kind: str) -> None:
        self.kind = kind
        super().__init__(item)

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
    ) -> "LfpJoinItem":
        return cls(item, match["kind"])

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            state = _state_from_message(interaction.message)
        except Exception:
            await interaction.response.send_message(
                "Nepodařilo se načíst stav události.", ephemeral=True
            )
            return

        if state.get("x"):
            await interaction.response.send_message(
                "Tato událost už byla zrušena.", ephemeral=True
            )
            return

        uid = str(interaction.user.id)
        on_time = list(state.get("ot", []))
        late = list(state.get("lt", []))
        capacity: Optional[int] = state.get("cap")

        if self.kind == "ontime":
            if _uid_in(on_time, uid):
                on_time = _remove_uid(on_time, uid)
                state["ot"] = on_time
                state["lt"] = late
                await interaction.response.edit_message(
                    view=LfpView(
                        state=state,
                        guild_id=interaction.guild_id or GUILD_ID,
                    )
                )
                await interaction.followup.send("Tvoje přihlášení bylo zrušeno.", ephemeral=True)
                return

            late = _remove_uid(late, uid)
            if capacity is not None and len(on_time) + len(late) >= capacity:
                await interaction.response.send_message(
                    f"Kapacita události je plná ({capacity} hráčů).",
                    ephemeral=True,
                )
                return

            on_time.append(uid)
            state["ot"] = on_time
            state["lt"] = late
            await interaction.response.edit_message(
                view=LfpView(
                    state=state,
                    guild_id=interaction.guild_id or GUILD_ID,
                )
            )
            await interaction.followup.send(
                "Přihlásil/a ses jako **přijdu včas**.",
                ephemeral=True,
            )
            return

        if _uid_in(late, uid):
            late = _remove_uid(late, uid)
            state["ot"] = on_time
            state["lt"] = late
            await interaction.response.edit_message(
                view=LfpView(
                    state=state,
                    guild_id=interaction.guild_id or GUILD_ID,
                )
            )
            await interaction.followup.send("Tvoje přihlášení bylo zrušeno.", ephemeral=True)
            return

        on_time = _remove_uid(on_time, uid)
        if capacity is not None and len(on_time) + len(late) >= capacity:
            await interaction.response.send_message(
                f"Kapacita události je plná ({capacity} hráčů).",
                ephemeral=True,
            )
            return

        await interaction.response.send_modal(
            LfpLateModal(source_message=interaction.message, uid=uid)
        )


class LfpLateModal(discord.ui.Modal, title="Přijdeš pozdě?"):
    def __init__(self, *, source_message: discord.Message, uid: str) -> None:
        super().__init__()
        self._source_message = source_message
        self._uid = uid

        self.delay_input = discord.ui.TextInput(
            style=discord.TextStyle.short,
            required=False,
            default="",
            placeholder="Například 5, 10, 15 nebo 30",
            max_length=10,
        )
        self.add_item(
            discord.ui.Label(
                text="Zpoždění v minutách (volitelné)",
                description="Když pole necháš prázdné, zapíše se jen pozdní příchod.",
                component=self.delay_input,
            )
        )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            state = _state_from_message(self._source_message)
        except Exception:
            await interaction.response.send_message(
                "Nepodařilo se načíst stav události.", ephemeral=True
            )
            return

        if state.get("x"):
            await interaction.response.send_message(
                "Tato událost už byla zrušena.", ephemeral=True
            )
            return

        on_time = _remove_uid(list(state.get("ot", [])), self._uid)
        late = _remove_uid(list(state.get("lt", [])), self._uid)

        delay_raw = self.delay_input.value.strip()
        entry = f"{self._uid}|+{delay_raw} min" if delay_raw else self._uid
        late.append(entry)

        state["ot"] = on_time
        state["lt"] = late

        await self._source_message.edit(
            view=LfpView(state=state, guild_id=self._source_message.guild.id)
        )

        suffix = f" (+{delay_raw} min)" if delay_raw else ""
        await interaction.response.send_message(
            f"Přihlásil/a ses jako **přijdu později**{suffix}.",
            ephemeral=True,
        )


class LfpManageView(discord.ui.View):
    def __init__(self, *, source_message: discord.Message, state: dict[str, Any]) -> None:
        super().__init__(timeout=120)
        self._source_message = source_message
        self._state = state

    @discord.ui.button(label="Upravit událost", style=discord.ButtonStyle.primary)
    async def edit_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await interaction.response.send_modal(
            LfpModal(source_message=self._source_message, prefill=self._state)
        )

    @discord.ui.button(label="Zrušit událost", style=discord.ButtonStyle.danger)
    async def cancel_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        try:
            state = _state_from_message(self._source_message)
        except Exception:
            await interaction.response.send_message(
                "Nepodařilo se načíst stav události.", ephemeral=True
            )
            return

        state["x"] = 1
        await self._source_message.edit(
            view=LfpView(state=state, guild_id=self._source_message.guild.id)
        )

        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(view=self)


class LfpModal(discord.ui.Modal, title="Hledám spoluhráče"):
    def __init__(
        self,
        *,
        source_message: Optional[discord.Message] = None,
        prefill: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__()
        self._source_message = source_message

        message_default = prefill.get("msg", "") if prefill else ""
        capacity_default = ""
        if prefill and prefill.get("cap") is not None:
            capacity_default = str(prefill["cap"])

        channel_default = DEFAULT_VOICE_CHANNEL_ID
        if prefill and prefill.get("ch"):
            channel_default = int(prefill["ch"])

        selected_day = "today"
        selected_time = "10:00"
        if prefill and prefill.get("ts"):
            event_dt = datetime.fromtimestamp(prefill["ts"], tz=PRAGUE_TZ)
            now = datetime.now(PRAGUE_TZ)
            if event_dt.date().toordinal() == now.date().toordinal() + 1:
                selected_day = "tomorrow"
            selected_time = event_dt.strftime("%H:%M")
            if selected_time not in _time_slot_values():
                selected_time = "10:00"

        self.message_input = discord.ui.TextInput(
            style=discord.TextStyle.paragraph,
            required=False,
            default=message_default,
            placeholder="Například hrajeme ranked, dorazte prosím včas.",
            max_length=500,
        )
        self.capacity_input = discord.ui.TextInput(
            style=discord.TextStyle.short,
            required=False,
            default=capacity_default,
            placeholder="Například 5",
            max_length=4,
        )
        self.date_select = discord.ui.Select(
            options=_date_options(selected_day),
            placeholder="Vyber den",
            min_values=1,
            max_values=1,
        )
        self.time_select = discord.ui.Select(
            options=_time_options(selected_time),
            placeholder="Vyber čas",
            min_values=1,
            max_values=1,
        )
        self.channel_select = discord.ui.ChannelSelect(
            custom_id="lfp_channel_select",
            channel_types=[discord.ChannelType.voice, discord.ChannelType.stage_voice],
            min_values=1,
            max_values=1,
            required=True,
            default_values=[_channel_default_value(channel_default)],
            placeholder="Vyber hlasový kanál pro sraz",
        )

        self.add_item(
            discord.ui.Label(
                text="Zpráva (volitelně)",
                description="Maximálně 500 znaků.",
                component=self.message_input,
            )
        )
        self.add_item(
            discord.ui.Label(
                text="Den",
                description="Pro tuto událost můžeš vybrat jen dnes nebo zítra.",
                component=self.date_select,
            )
        )
        self.add_item(
            discord.ui.Label(
                text="Čas",
                description="Časy jsou po 30 minutách od 10:00 do 22:00.",
                component=self.time_select,
            )
        )
        self.add_item(
            discord.ui.Label(
                text="Hlasový kanál pro sraz",
                description="Předvyplněný je výchozí kanál.",
                component=self.channel_select,
            )
        )
        self.add_item(
            discord.ui.Label(
                text="Maximální počet hráčů (volitelně)",
                description="Když pole necháš prázdné, kapacita bude neomezená.",
                component=self.capacity_input,
            )
        )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not self.date_select.values:
            await interaction.response.send_message("Vyber prosím den srazu.", ephemeral=True)
            return

        if not self.time_select.values:
            await interaction.response.send_message("Vyber prosím čas srazu.", ephemeral=True)
            return

        capacity: Optional[int] = None
        capacity_raw = self.capacity_input.value.strip()
        if capacity_raw:
            try:
                capacity = int(capacity_raw)
                if capacity < 1:
                    raise ValueError
            except ValueError:
                await interaction.response.send_message(
                    "Kapacita musí být kladné celé číslo.",
                    ephemeral=True,
                )
                return

        if not self.channel_select.values:
            await interaction.response.send_message(
                "Vyber prosím hlasový kanál pro sraz.",
                ephemeral=True,
            )
            return

        channel_id = self.channel_select.values[0].id
        message_text = self.message_input.value.strip()
        event_dt = _event_datetime_from_selects(
            self.date_select.values[0],
            self.time_select.values[0],
        )
        event_ts = int(event_dt.timestamp())

        if self._source_message is not None:
            try:
                previous_state = _state_from_message(self._source_message)
            except Exception:
                await interaction.response.send_message(
                    "Nepodařilo se načíst původní stav události.",
                    ephemeral=True,
                )
                return

            state: dict[str, Any] = {
                "cid": previous_state["cid"],
                "cn": interaction.user.display_name,
                "msg": message_text,
                "ts": event_ts,
                "ch": channel_id,
                "ot": list(previous_state.get("ot", [])),
                "lt": list(previous_state.get("lt", [])),
            }
            if capacity is not None:
                state["cap"] = capacity
            if previous_state.get("x"):
                state["x"] = 1

            await self._source_message.edit(
                view=LfpView(state=state, guild_id=self._source_message.guild.id)
            )
            await interaction.response.send_message("Událost byla upravena.", ephemeral=True)
            return

        state: dict[str, Any] = {
            "cid": interaction.user.id,
            "cn": interaction.user.display_name,
            "msg": message_text,
            "ts": event_ts,
            "ch": channel_id,
            "ot": [],
            "lt": [],
        }
        if capacity is not None:
            state["cap"] = capacity

        await interaction.response.send_message(
            view=LfpView(state=state, guild_id=interaction.guild_id or GUILD_ID)
        )

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        if interaction.response.is_done():
            await interaction.followup.send(f"Nastala chyba: {error}", ephemeral=True)
        else:
            await interaction.response.send_message(f"Nastala chyba: {error}", ephemeral=True)


@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.command(
    name="hledam-spoluhrace",
    description="Vytvoří příspěvek pro hledání spoluhráčů.",
)
async def hledam_spoluhrace(interaction: discord.Interaction) -> None:
    await interaction.response.send_modal(LfpModal())
