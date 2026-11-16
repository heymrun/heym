export interface GmailLabel {
  id: string;
  name: string;
}

export interface GmailAddress {
  email: string;
  display_name: string;
  is_primary: boolean;
}
