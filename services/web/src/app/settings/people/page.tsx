import { PeopleSettings } from "@/features/people";
import { AuthGuard } from "@/components/AuthGuard";

export default function PeoplePage() {
  return (
    <AuthGuard>
      <div className="max-w-7xl mx-auto px-4 py-8">
        <PeopleSettings />
      </div>
    </AuthGuard>
  );
}
