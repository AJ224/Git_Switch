from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from tkinter import ttk


@dataclass(frozen=True)
class ThemePalette:
    name: str
    bg: str
    surface: str
    border: str
    text: str
    muted: str
    accent: str
    accent_text: str
    success: str
    danger: str
    badge_bg: str
    badge_text: str
    list_bg: str
    list_fg: str
    list_select_bg: str
    list_select_fg: str


LIGHT = ThemePalette(
    name="light",
    bg="#f4f6f8",
    surface="#ffffff",
    border="#d7dde5",
    text="#1f2937",
    muted="#64748b",
    accent="#0f766e",
    accent_text="#ffffff",
    success="#15803d",
    danger="#b91c1c",
    badge_bg="#e2e8f0",
    badge_text="#334155",
    list_bg="#ffffff",
    list_fg="#1f2937",
    list_select_bg="#ccfbf1",
    list_select_fg="#134e4a",
)

DARK = ThemePalette(
    name="dark",
    bg="#111827",
    surface="#1f2937",
    border="#374151",
    text="#f9fafb",
    muted="#9ca3af",
    accent="#14b8a6",
    accent_text="#042f2e",
    success="#4ade80",
    danger="#f87171",
    badge_bg="#374151",
    badge_text="#e5e7eb",
    list_bg="#111827",
    list_fg="#f9fafb",
    list_select_bg="#115e59",
    list_select_fg="#ecfeff",
)


class ThemeManager:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.style = ttk.Style(root)
        self.current = LIGHT

    def apply(self, palette: ThemePalette) -> None:
        self.current = palette
        self.root.configure(bg=palette.bg)
        self.style.theme_use("clam")

        self.style.configure(".", background=palette.bg, foreground=palette.text)
        self.style.configure("TFrame", background=palette.bg)
        self.style.configure("Card.TFrame", background=palette.surface, relief="flat")
        self.style.configure("Surface.TFrame", background=palette.surface)
        self.style.configure("TLabel", background=palette.bg, foreground=palette.text)
        self.style.configure("Card.TLabel", background=palette.surface, foreground=palette.text)
        self.style.configure("Muted.TLabel", background=palette.bg, foreground=palette.muted)
        self.style.configure("CardMuted.TLabel", background=palette.surface, foreground=palette.muted)
        self.style.configure("Title.TLabel", background=palette.bg, foreground=palette.text, font=("", 16, "bold"))
        self.style.configure("Subtitle.TLabel", background=palette.bg, foreground=palette.muted)
        self.style.configure("Section.TLabel", background=palette.surface, foreground=palette.text, font=("", 11, "bold"))
        self.style.configure("Active.TLabel", background=palette.surface, foreground=palette.success, font=("", 11, "bold"))
        self.style.configure("Status.TLabel", background=palette.surface, foreground=palette.text)
        self.style.configure("Error.TLabel", background=palette.surface, foreground=palette.danger)
        self.style.configure("Badge.TLabel", background=palette.badge_bg, foreground=palette.badge_text, padding=(8, 2))
        self.style.configure("TLabelframe", background=palette.surface, foreground=palette.text, bordercolor=palette.border)
        self.style.configure("TLabelframe.Label", background=palette.surface, foreground=palette.text)
        self.style.configure(
            "TEntry",
            fieldbackground=palette.surface,
            foreground=palette.text,
            bordercolor=palette.border,
            lightcolor=palette.border,
            darkcolor=palette.border,
            padding=(8, 7),
            font=("", 11),
        )
        self.style.map(
            "TEntry",
            bordercolor=[("focus", palette.accent)],
            lightcolor=[("focus", palette.accent)],
            darkcolor=[("focus", palette.accent)],
        )
        self.style.configure("TRadiobutton", background=palette.surface, foreground=palette.text)
        self.style.configure("TCheckbutton", background=palette.surface, foreground=palette.text)
        self.style.configure("TButton", padding=(12, 7), font=("", 10))
        self.style.configure(
            "Accent.TButton",
            background=palette.accent,
            foreground=palette.accent_text,
            padding=(14, 8),
            font=("", 10, "bold"),
        )
        self.style.map("Accent.TButton", background=[("active", palette.accent), ("disabled", palette.border)])
        self.style.configure("Secondary.TButton", background=palette.surface, foreground=palette.text)
        self.style.configure("Danger.TButton", foreground=palette.danger)

    def bind_listbox(self, listbox: tk.Listbox) -> None:
        palette = self.current
        listbox.configure(
            bg=palette.list_bg,
            fg=palette.list_fg,
            selectbackground=palette.list_select_bg,
            selectforeground=palette.list_select_fg,
            highlightthickness=1,
            highlightbackground=palette.border,
            highlightcolor=palette.accent,
            relief="flat",
            borderwidth=0,
        )


def toggle_theme(current: str) -> ThemePalette:
    return DARK if current == "light" else LIGHT
