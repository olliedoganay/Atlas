import { useEffect, useRef, useState } from "react";
import { ChevronDown, Lock, Settings as SettingsIcon, Unlock, User } from "lucide-react";
import { useNavigate } from "react-router-dom";

import type { UserSummary } from "../lib/api";

export function ProfileMenu({
  users,
  currentUserId,
  onPick,
  onUnlock,
}: {
  users: UserSummary[];
  currentUserId: string;
  onPick: (userId: string) => void;
  onUnlock: (userId: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement | null>(null);
  const navigate = useNavigate();

  const current = users.find((u) => u.user_id === currentUserId);
  const label = currentUserId || "No profile";
  const initial = (currentUserId || "?").slice(0, 1).toUpperCase();

  useEffect(() => {
    if (!open) {
      return;
    }
    const handleClick = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
      }
    };
    window.addEventListener("mousedown", handleClick);
    window.addEventListener("keydown", handleKey);
    return () => {
      window.removeEventListener("mousedown", handleClick);
      window.removeEventListener("keydown", handleKey);
    };
  }, [open]);

  return (
    <div className="profile-menu" ref={ref}>
      <button
        aria-expanded={open}
        aria-haspopup="menu"
        className="profile-menu-trigger"
        onClick={() => setOpen((prev) => !prev)}
        type="button"
        title="Switch profile"
      >
        <div className="profile-menu-avatar">{initial}</div>
        <div className="profile-menu-copy">
          <strong>{label}</strong>
          <span>{current ? (current.protection === "password" ? "Password protected" : "Active profile") : "Tap to choose"}</span>
        </div>
        <ChevronDown className="profile-menu-chevron" size={16} />
      </button>

      {open ? (
        <div className="profile-menu-pop" role="menu">
          {users.length === 0 ? (
            <div className="profile-menu-empty">No profiles yet. Create one in Settings.</div>
          ) : (
            users.map((user) => {
              const isActive = user.user_id === currentUserId;
              const isLocked = Boolean(user.locked);
              return (
                <button
                  className={`profile-menu-item${isActive ? " active" : ""}`}
                  key={user.user_id}
                  onClick={() => {
                    setOpen(false);
                    if (isLocked) {
                      onUnlock(user.user_id);
                    } else {
                      onPick(user.user_id);
                    }
                  }}
                  role="menuitem"
                  type="button"
                >
                  <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
                    {user.protection === "password" ? (isLocked ? <Lock size={14} /> : <Unlock size={14} />) : <User size={14} />}
                    {user.user_id}
                  </span>
                  <span className="profile-menu-item-meta">
                    {isLocked ? "Locked" : isActive ? "Current" : ""}
                  </span>
                </button>
              );
            })
          )}
          <div className="profile-menu-divider" />
          <button
            className="profile-menu-link"
            onClick={() => {
              setOpen(false);
              navigate("/settings");
            }}
            role="menuitem"
            type="button"
          >
            <SettingsIcon size={14} />
            Manage profiles
          </button>
        </div>
      ) : null}
    </div>
  );
}
