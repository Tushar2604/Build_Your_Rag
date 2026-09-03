"""The receptionist's working memory for one booking conversation.

A booking is never one message. It is "I'd like an appointment", then a service,
then a day, then a number from a list, then a name, then a phone — six turns, and
each of them arrives as a *separate* agent run with nothing but the rendered chat
transcript for memory. The transcript records what was *said*; it does not record
the service id, the branch id, or the exact instant behind "Thu 03 Sep, 9:00 AM".

Without somewhere to keep those, every turn had to re-derive them by calling
`find_available_slots` again — and that call's whole purpose is to produce a
numbered list to read out, so the agent dutifully read it out again. That is the
loop a real customer hit: four times offered, a number chosen, the same four
times offered back. It could never book, because by the time it had the name and
the phone it no longer knew which slot the "1" had meant.

The slate is that missing memory, and it is deliberately *data*, not prose:

  * The numbered options carry their exact `starts_at`, so the number a customer
    replies with resolves to an instant by lookup rather than by a model
    re-reading its own earlier message.
  * Resolution is arithmetic (`resolve`) — "2", "the 10", "10am" and the full
    label all land on the same option, and an unrecognisable reply returns None
    rather than a guess.
  * `missing_for_booking` is computed, so the agent is *told* it has everything
    it needs instead of being trusted to notice.

Nothing here can invent a time: every option is put on the slate by
`find_available_slots`, straight from the availability engine.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

# How long an offered list stays answerable. A customer who replies "2" forty
# minutes later is still answering the list they were sent; one who comes back
# the next morning is not, and re-checking is the honest thing to do — the slot
# may well be gone by then.
OFFER_TTL = timedelta(minutes=45)

# Bounded because this is serialised into every prompt of the conversation. Four
# are offered; the rest are the "anything later?" alternatives, which are worth
# keeping resolvable but not worth unbounded prompt growth.
MAX_REMEMBERED_OPTIONS = 12

_ORDINALS = {
    "first": 1,
    "1st": 1,
    "second": 2,
    "2nd": 2,
    "third": 3,
    "3rd": 3,
    "fourth": 4,
    "4th": 4,
}

# "2", "#2", "option 2", "no. 2", "number 2" — the shapes a person actually
# sends when asked to reply with a number.
_OPTION_NUMBER = re.compile(
    r"^(?:option|opt|no\.?|number|#)?\s*(\d{1,2})\.?$", re.IGNORECASE
)

# A clock time inside free text: "10am", "9:15", "12 pm", "the 10".
_CLOCK = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", re.IGNORECASE)

# Five or more digits in a row is a phone number, an order id or a date — never a
# time. Without this guard, "91220910827" resolves to an appointment.
_LONG_DIGIT_RUN = re.compile(r"\d{5,}")


def _ensure_utc(value: datetime) -> datetime:
    """A naive instant is read as UTC — every instant in this system is."""
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _as_utc(value: datetime | None) -> datetime | None:
    return None if value is None else _ensure_utc(value)


def _read_dt(raw: Any) -> datetime | None:
    """Parse an ISO instant out of stored JSON, tolerating anything else."""
    if isinstance(raw, datetime):
        return _as_utc(raw)
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        return _as_utc(datetime.fromisoformat(raw.strip().replace("Z", "+00:00")))
    except ValueError:
        return None


@dataclass(frozen=True)
class SlateOption:
    """One numbered time the customer was actually shown.

    `starts_at` is the engine's instant and the only thing ever passed back to a
    tool. `label`, `local_hour` and `local_minute` are the branch-local rendering
    the customer saw, kept so a reply of "10am" can be matched against what was
    on their screen rather than against UTC.
    """

    option: int
    label: str
    starts_at: datetime
    ends_at: datetime | None = None
    local_hour: int = 0
    local_minute: int = 0
    resource_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "option": self.option,
            "label": self.label,
            "starts_at": self.starts_at.isoformat(),
            "ends_at": self.ends_at.isoformat() if self.ends_at else None,
            "local_hour": self.local_hour,
            "local_minute": self.local_minute,
            "resource_ids": list(self.resource_ids),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> SlateOption | None:
        starts_at = _read_dt(raw.get("starts_at"))
        if starts_at is None:
            return None
        try:
            option = int(raw.get("option") or 0)
        except (TypeError, ValueError):
            return None
        return cls(
            option=option,
            label=str(raw.get("label") or ""),
            starts_at=starts_at,
            ends_at=_read_dt(raw.get("ends_at")),
            local_hour=int(raw.get("local_hour") or 0),
            local_minute=int(raw.get("local_minute") or 0),
            resource_ids=[str(r) for r in (raw.get("resource_ids") or [])],
        )


@dataclass
class BookingSlate:
    """Where one conversation's booking has got to.

    Mutable on purpose: the tools that learn something during a run write it here
    and the use case persists the result once, at the end. Every field is
    optional, so a conversation that never mentions an appointment simply carries
    an empty slate that renders to nothing.
    """

    service_id: str = ""
    service_name: str = ""
    location_id: str = ""
    location_name: str = ""
    timezone: str = ""
    options: list[SlateOption] = field(default_factory=list)
    offered_at: datetime | None = None
    chosen: SlateOption | None = None
    hold_token: str = ""
    hold_expires_at: datetime | None = None
    customer_name: str = ""
    customer_phone: str = ""
    customer_email: str = ""
    reason_for_visit: str = ""
    # Set by the tool that books, read by the prompt: an assistant that has just
    # booked must confirm, not start collecting details for a booking that is
    # already done.
    last_reference: str = ""

    # --- writes made by the tools -------------------------------------------

    def offer(
        self,
        *,
        service_id: str,
        service_name: str,
        location_id: str,
        location_name: str,
        timezone: str,
        options: list[SlateOption],
        now: datetime,
    ) -> None:
        """Record the list the customer is about to be shown.

        A change of service or branch clears the choice and the hold: the times
        on the old slate belong to a different appointment, and silently keeping
        "they chose 2" across that change is how a customer ends up booked for
        something they did not ask for.
        """
        if service_id != self.service_id or location_id != self.location_id:
            self.chosen = None
            self.hold_token = ""
            self.hold_expires_at = None
        self.service_id = service_id
        self.service_name = service_name
        self.location_id = location_id
        self.location_name = location_name
        self.timezone = timezone
        self.options = options[:MAX_REMEMBERED_OPTIONS]
        self.offered_at = _as_utc(now)
        self.last_reference = ""
        # A choice that is no longer on offer is not a choice. Dropping it is
        # what makes "that slot just went" a visible state rather than a booking
        # attempt against a time nobody can have.
        if self.chosen and all(
            option.starts_at != self.chosen.starts_at for option in self.options
        ):
            self.chosen = None
            self.hold_token = ""
            self.hold_expires_at = None

    def choose(self, option: SlateOption) -> None:
        self.chosen = option

    def hold(self, *, token: str, expires_at: datetime | None) -> None:
        self.hold_token = token
        self.hold_expires_at = _as_utc(expires_at)

    def remember(
        self,
        *,
        name: str = "",
        phone: str = "",
        email: str = "",
        reason: str = "",
    ) -> None:
        """Keep details the customer has already given.

        Never unsets a known one — a tool call that simply omitted a field must
        not erase what an earlier turn was told.
        """
        self.customer_name = name.strip() or self.customer_name
        self.customer_phone = phone.strip() or self.customer_phone
        self.customer_email = email.strip() or self.customer_email
        self.reason_for_visit = reason.strip() or self.reason_for_visit

    def booked(self, reference: str) -> None:
        """The appointment exists. Everything about *making* it is now stale.

        Who the customer is survives, so a second booking in the same thread does
        not re-ask for a name and a number the assistant was just given.
        """
        self.options = []
        self.offered_at = None
        self.chosen = None
        self.hold_token = ""
        self.hold_expires_at = None
        self.reason_for_visit = ""
        self.last_reference = reference

    # --- reads ---------------------------------------------------------------

    def fresh_options(self, now: datetime) -> list[SlateOption]:
        """The offered list, if it is still recent enough to be an answer to."""
        if not self.options or self.offered_at is None:
            return []
        if _ensure_utc(now) - self.offered_at > OFFER_TTL:
            return []
        return list(self.options)

    def live_hold(self, now: datetime) -> str:
        """The hold token, only while the hold actually still exists."""
        if not self.hold_token:
            return ""
        if self.hold_expires_at is not None and self.hold_expires_at <= _ensure_utc(now):
            return ""
        return self.hold_token

    def resolve(self, value: Any, now: datetime) -> SlateOption | None:
        """Turn whatever the customer (or the model) said into one offered option.

        Deliberately conservative. A reply this cannot read returns None, and the
        caller asks rather than books the wrong time — an appointment made from a
        guess is worse than one more question.
        """
        options = self.fresh_options(now)
        if not options:
            return None
        if isinstance(value, bool):  # `True` is an int; it is not option 1.
            return None
        if isinstance(value, int):
            return next((o for o in options if o.option == value), None)

        text = str(value or "").strip()
        if not text:
            return None
        lowered = " ".join(text.lower().split())

        # The label read back verbatim ("Thu 03 Sep, 9:00 AM works for me").
        for option in options:
            if option.label and " ".join(option.label.lower().split()) in lowered:
                return option

        number = _OPTION_NUMBER.match(lowered)
        if number:
            match = next(
                (o for o in options if o.option == int(number.group(1))), None
            )
            if match is not None:
                return match

        for word, ordinal in _ORDINALS.items():
            if re.search(rf"\b{re.escape(word)}\b", lowered):
                match = next((o for o in options if o.option == ordinal), None)
                if match is not None:
                    return match

        return self._resolve_clock(lowered, options)

    @staticmethod
    def _resolve_clock(lowered: str, options: list[SlateOption]) -> SlateOption | None:
        """Match a spoken time ("10am", "9:15", "the 10") against what was offered.

        Only ever returns an unambiguous match. "10" when both 10:00 and 22:00
        are free is a question, not an answer.
        """
        if _LONG_DIGIT_RUN.search(lowered):
            return None  # A phone number is not a time.
        for raw_hour, raw_minute, meridiem in _CLOCK.findall(lowered):
            hour = int(raw_hour)
            if not 0 <= hour <= 23:
                continue
            minute = int(raw_minute) if raw_minute else None
            if meridiem:
                base = hour % 12
                candidates = [base + 12] if meridiem.lower() == "pm" else [base]
            else:
                # No am/pm: accept either reading, but only if exactly one of
                # them is actually on offer.
                candidates = sorted({hour % 24, (hour % 12) + 12})
            hits = [
                option
                for option in options
                if option.local_hour in candidates
                and (minute is None or option.local_minute == minute)
            ]
            if len(hits) == 1:
                return hits[0]
        return None

    def missing_for_booking(self) -> list[str]:
        """What `book_appointment` would still reject, in the customer's terms."""
        missing = []
        if not (self.service_id and self.location_id):
            missing.append("which service and branch")
        if self.chosen is None:
            missing.append("which time they want")
        if not self.customer_name:
            missing.append("their name")
        if not (self.customer_phone or self.customer_email):
            missing.append("a phone number or email")
        return missing

    def is_empty(self) -> bool:
        return not self.to_dict()

    # --- rendering & serialisation -------------------------------------------

    def render(self, now: datetime) -> str:
        """The block the agent reads at the top of every turn.

        Written as facts plus one instruction, because the failure this replaces
        was not the model lacking data — it was the model re-deriving data it had
        already been given, and re-deriving availability means re-offering it.
        """
        if self.is_empty():
            return (
                "(Nothing yet — this conversation has not got as far as a service, "
                "a branch or a time.)"
            )

        lines: list[str] = []
        if self.service_id:
            lines.append(
                f"  Service: {self.service_name or 'chosen'} "
                f"[service_id={self.service_id}]"
            )
        if self.location_id:
            lines.append(
                f"  Branch: {self.location_name or 'chosen'} "
                f"[location_id={self.location_id}], times shown in "
                f"{self.timezone or 'UTC'}"
            )

        options = self.fresh_options(now)
        if options:
            lines.append(
                "  Times you have ALREADY offered them — these are the numbers "
                "they are replying to. Do not look them up again:"
            )
            lines.extend(
                f"    {option.option}. {option.label} "
                f"(starts_at={option.starts_at.isoformat()})"
                for option in options
            )
        elif self.options:
            lines.append(
                "  The times you offered earlier are now too old to trust — call "
                "find_available_slots again before offering anything."
            )

        if self.chosen is not None:
            lines.append(
                f"  They have CHOSEN option {self.chosen.option}: {self.chosen.label} "
                f"(starts_at={self.chosen.starts_at.isoformat()}). Do not ask them "
                "to pick again."
            )
        if self.live_hold(now):
            expiry = (
                self.hold_expires_at.isoformat() if self.hold_expires_at else "shortly"
            )
            lines.append(
                f"  That slot is held for them until {expiry} — a hold is NOT a "
                "booking."
            )
        if self.customer_name:
            lines.append(f"  Name: {self.customer_name} — do not ask again.")
        if self.customer_phone:
            lines.append(f"  Phone: {self.customer_phone} — do not ask again.")
        if self.customer_email:
            lines.append(f"  Email: {self.customer_email} — do not ask again.")
        if self.reason_for_visit:
            lines.append(
                f"  Reason for visit: {self.reason_for_visit} — do not ask again."
            )
        if self.last_reference:
            lines.append(
                f"  ALREADY BOOKED in this conversation: {self.last_reference}. "
                "Confirm it if they ask; do not book it a second time."
            )

        missing = self.missing_for_booking()
        if self.chosen is not None and not missing:
            lines.append(
                "  You have everything book_appointment needs. Call it NOW — do "
                "not ask another question first."
            )
        elif missing:
            lines.append("  Still needed before booking: " + ", ".join(missing) + ".")

        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """Only what is set, so an untouched slate serialises to `{}` — which is
        how the use case tells "nothing happened" from "cleared"."""
        data: dict[str, Any] = {}
        for key in (
            "service_id",
            "service_name",
            "location_id",
            "location_name",
            "timezone",
            "hold_token",
            "customer_name",
            "customer_phone",
            "customer_email",
            "reason_for_visit",
            "last_reference",
        ):
            value = getattr(self, key)
            if value:
                data[key] = value
        if self.options:
            data["options"] = [option.to_dict() for option in self.options]
        if self.offered_at:
            data["offered_at"] = self.offered_at.isoformat()
        if self.chosen is not None:
            data["chosen"] = self.chosen.to_dict()
        if self.hold_expires_at:
            data["hold_expires_at"] = self.hold_expires_at.isoformat()
        return data

    @classmethod
    def from_dict(cls, raw: Any) -> BookingSlate:
        """Rebuild from stored JSON, never raising.

        A slate that cannot be read is a slate the conversation starts without —
        which is exactly how the system behaved before it existed. Losing the
        working state of one conversation is not worth a 500 on an inbound
        WhatsApp message.
        """
        if not isinstance(raw, dict):
            return cls()
        try:
            options = [
                option
                for option in (
                    SlateOption.from_dict(item)
                    for item in raw.get("options") or []
                    if isinstance(item, dict)
                )
                if option is not None
            ]
            chosen_raw = raw.get("chosen")
            chosen = (
                SlateOption.from_dict(chosen_raw)
                if isinstance(chosen_raw, dict)
                else None
            )
            return cls(
                service_id=str(raw.get("service_id") or ""),
                service_name=str(raw.get("service_name") or ""),
                location_id=str(raw.get("location_id") or ""),
                location_name=str(raw.get("location_name") or ""),
                timezone=str(raw.get("timezone") or ""),
                options=options[:MAX_REMEMBERED_OPTIONS],
                offered_at=_read_dt(raw.get("offered_at")),
                chosen=chosen,
                hold_token=str(raw.get("hold_token") or ""),
                hold_expires_at=_read_dt(raw.get("hold_expires_at")),
                customer_name=str(raw.get("customer_name") or ""),
                customer_phone=str(raw.get("customer_phone") or ""),
                customer_email=str(raw.get("customer_email") or ""),
                reason_for_visit=str(raw.get("reason_for_visit") or ""),
                last_reference=str(raw.get("last_reference") or ""),
            )
        except (TypeError, ValueError):
            return cls()
