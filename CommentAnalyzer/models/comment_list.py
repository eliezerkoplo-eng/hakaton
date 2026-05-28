from CommentAnalyzer.models.comment import Comment


class CommentList:
    def __init__(self, comments: list = None):
        self.comments = comments if comments is not None else []

    def add_comment(self, comment: Comment) -> None:
        self.comments.append(comment)

    def remove_comment(self, comment: Comment) -> None:
        if comment in self.comments:
            self.comments.remove(comment)

    def remove_comment_by_id(self, comment_id: str) -> None:
        self.comments = [c for c in self.comments if c.id != comment_id]

    def get_all_authors(self) -> list:
        return [c.author for c in self.comments]

    def get_all_timestamps(self) -> list:
        return [c.created_utc for c in self.comments]

    def sort_by_time(self) -> None:
        self.comments.sort(key=lambda c: c.created_utc)

    def size(self) -> int:
        return len(self.comments)

    def get_all_comments(self) -> list:
        return self.comments

    def get_comments_by_author(self, author_name: str) -> list:
        return [c for c in self.comments if c.author == author_name]
