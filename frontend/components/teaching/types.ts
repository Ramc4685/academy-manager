export interface VideoLink {
  title: string;
  url: string;
}

export type ResourceLinkKind = "YOUTUBE" | "PDF_REFERENCE";

export interface ResourceLink {
  kind: ResourceLinkKind;
  title: string;
  url: string | null;
}

export interface LessonCard {
  card_id: string;
  lesson_number: number;
  title: string;
  goal_summary: string;
  teaching_points: string[];
  equipment: string[];
  activity_summary: string;
  safety_notes: string[];
  source: string;
  module_name: string;
  lesson_range: string;
  page_hint: string | null;
  resource_links: ResourceLink[];
}

export type TeachingFocus = "practice" | "review" | "ready_for_level_up";

export interface NextSkill {
  skill_id: string;
  name: string;
  sequence: number;
  level_id: string;
  status: string;
  is_review: boolean;
  criteria: string[];
  youtube_links: VideoLink[];
}

export interface TeachingStudentFocus {
  student_id: string;
  student_name: string;
  next_skill: NextSkill | null;
  focus: TeachingFocus;
}

export interface TeachingUnplacedStudent {
  student_id: string;
  student_name: string;
}

export interface LevelTeachingGroup {
  level_id: string;
  level_name: string;
  level_sequence: number;
  youtube_links: VideoLink[];
  lesson_card: LessonCard | null;
  students: TeachingStudentFocus[];
}
