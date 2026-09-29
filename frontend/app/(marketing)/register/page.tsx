import { publicPageBrand } from "@/lib/public-page/metadata";
import { loadPublicAcademyPage } from "@/lib/public-page/server-fetch";

import RegisterPage from "./register-client";

/**
 * Row 15: server wrapper so the register header can show the academy's name
 * and mark on an academy host (`CourtMastr` on the platform host, unchanged).
 * Shares the same cached per-request read `/` and its metadata use.
 */
export default async function Register() {
  const { result } = await loadPublicAcademyPage();
  const academy = publicPageBrand(result);
  return (
    <RegisterPage
      academyName={academy?.name ?? null}
      logoUrl={academy?.logo_url ?? null}
      brandColor={academy?.brand_color ?? null}
    />
  );
}
