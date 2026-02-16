"use client";

import { useState, useRef, useEffect } from "react";
import { usePeople } from "../hooks/usePeople";
import type { PersonSummary } from "@/lib/types";

function PersonCard({
  person,
  onRename,
  isRenaming,
}: {
  person: PersonSummary;
  onRename: (id: string, label: string | null) => Promise<void>;
  isRenaming: boolean;
}) {
  const [isEditing, setIsEditing] = useState(false);
  const [editValue, setEditValue] = useState(person.label ?? "");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (isEditing && inputRef.current) {
      inputRef.current.focus();
      inputRef.current.select();
    }
  }, [isEditing]);

  const handleSave = async () => {
    const trimmed = editValue.trim();
    const newLabel = trimmed || null;
    if (newLabel !== person.label) {
      await onRename(person.person_cluster_id, newLabel);
    }
    setIsEditing(false);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") {
      handleSave();
    } else if (e.key === "Escape") {
      setEditValue(person.label ?? "");
      setIsEditing(false);
    }
  };

  const displayName = person.label || `Person ${person.person_cluster_id.slice(-4)}`;
  const initials = person.label
    ? person.label
        .split(/\s+/)
        .map((w) => w[0])
        .join("")
        .toUpperCase()
        .slice(0, 2)
    : "?";

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-4 hover:shadow-md transition-shadow">
      <div className="flex items-start gap-3">
        <div className="w-12 h-12 rounded-full bg-primary-600/10 flex items-center justify-center flex-shrink-0">
          <span className="text-sm font-semibold text-primary-600">
            {initials}
          </span>
        </div>
        <div className="flex-1 min-w-0">
          {isEditing ? (
            <input
              ref={inputRef}
              type="text"
              value={editValue}
              onChange={(e) => setEditValue(e.target.value)}
              onBlur={handleSave}
              onKeyDown={handleKeyDown}
              disabled={isRenaming}
              maxLength={100}
              placeholder="Enter name..."
              className="w-full px-2 py-1 text-sm font-medium text-gray-900 border border-primary-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent"
            />
          ) : (
            <button
              type="button"
              onClick={() => {
                setEditValue(person.label ?? "");
                setIsEditing(true);
              }}
              className="text-left w-full group"
            >
              <span
                className={`text-sm font-medium block truncate ${
                  person.label
                    ? "text-gray-900"
                    : "text-gray-400 italic"
                } group-hover:text-primary-600 transition-colors`}
              >
                {displayName}
              </span>
            </button>
          )}
          <div className="flex items-center gap-3 mt-1">
            <span className="inline-flex items-center text-xs text-gray-500">
              <svg
                className="w-3.5 h-3.5 mr-1 text-gray-400"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"
                />
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"
                />
              </svg>
              {person.face_count} scene{person.face_count !== 1 ? "s" : ""}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}

export function PeopleSettings() {
  const { people, isLoading, error, renamePerson, isRenaming } = usePeople();

  return (
    <div>
      <div className="mb-6">
        <h2 className="text-2xl font-bold text-gray-900">People</h2>
        <p className="text-sm text-gray-500 mt-1">
          Manage detected face clusters and assign names. Click a name to edit.
        </p>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
          {error}
        </div>
      )}

      {isLoading ? (
        <div className="text-center py-12 text-gray-500">
          Loading people...
        </div>
      ) : people.length === 0 ? (
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 text-center py-12">
          <svg
            className="w-12 h-12 mx-auto text-gray-300 mb-3"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={1.5}
              d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z"
            />
          </svg>
          <p className="text-gray-500">No people detected yet.</p>
          <p className="text-sm text-gray-400 mt-1">
            Ingest videos with face clustering enabled to see detected people
            here.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {people.map((person) => (
            <PersonCard
              key={person.person_cluster_id}
              person={person}
              onRename={renamePerson}
              isRenaming={isRenaming}
            />
          ))}
        </div>
      )}
    </div>
  );
}
